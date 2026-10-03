"""Resumable contribution workflow composed from the existing agent services."""

from __future__ import annotations

import json
import asyncio
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runtime import AgentRuntime, Budget, BudgetExceededError
from app.agent_tools import build_repository_tool_registry
from app.agent_service import (
    analyze_issue,
    create_pull_request,
    generate_acceptance_criteria,
    generate_regression_test,
    review_patch,
    _clone_or_update,
)
from app.models import AgentApproval, AgentReviewFinding, AgentRun, AgentStep, Issue as IssueModel, PullRequest
from app.memory_service import context_for, remember
from app.sandbox_service import run_sandbox_validation, run_sandbox_validation_with_auto_heal

logger = logging.getLogger(__name__)
MAX_PATCH_FILES = 20
MAX_PATCH_CHARS = 250_000


class ContributionAgent:
    """Run the contribution lifecycle and persist every resumable checkpoint."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.runtime = AgentRuntime(session)
        self.tools = build_repository_tool_registry()

    async def start(self, issue_id: int, idempotency_key: str) -> AgentRun:
        issue = await self.session.get(IssueModel, issue_id)
        if issue is None:
            raise ValueError(f"Issue not found: {issue_id}")
        from app.github_service import GitHubService

        issue_state = await asyncio.to_thread(
            GitHubService().get_issue_state, issue.repository, issue.number
        )
        if issue_state != "open":
            issue.is_suitable = False
            issue.agent_status = "stale"
            await self.session.commit()
            raise ValueError(f"Issue #{issue.number} is no longer open on GitHub")
        run = await self.runtime.create_run(
            idempotency_key=idempotency_key,
            issue_id=issue.id,
            repository=issue.repository,
            budget=Budget(
                max_model_requests=30,
                max_tokens=100_000,
                max_attempts=3,
            ),
        )
        await self.session.commit()
        return run

    async def execute(self, run_id: int) -> AgentRun:
        run = await self.session.get(AgentRun, run_id)
        if run is None:
            raise ValueError(f"Agent run not found: {run_id}")
        if run.status in {"awaiting_approval", "monitoring_ci", "completed", "cancelled"}:
            return run

        issue = await self.session.get(IssueModel, run.issue_id)
        if issue is None:
            await self._fail(run, "Issue no longer exists")
            return run

        try:
            await self.runtime.transition(run, "planning")
            await self.session.commit()
            repository_memory = await context_for(self.session, issue.repository)
            repository_root = await asyncio.to_thread(_clone_or_update, issue.repository)
            inventory = await self.runtime.execute_tool(
                run,
                self.tools,
                "list_repository_files",
                {"repository_root": str(repository_root), "pattern": "**/*.py", "limit": 200},
            )

            acceptance = await self._run_step(
                run,
                "acceptance_criteria",
                {"issue_id": issue.id, "repository_files": inventory["files"]},
                generate_acceptance_criteria(
                    issue.repository,
                    issue.number,
                    issue.title,
                    issue.body or "",
                    repository_memory,
                ),
                tokens=1024,
            )
            if not acceptance.get("is_actionable", False):
                await self._fail(run, "Issue is not actionable without maintainer clarification")
                return run

            regression: dict[str, Any] = {}
            before_result: dict[str, Any] = {}
            regression_step_key = "regression_test"
            for regression_attempt in range(1, 4):
                regression_step_key = (
                    "regression_test"
                    if regression_attempt == 1
                    else f"regression_test_retry_{regression_attempt}"
                )
                feedback = (
                    ""
                    if regression_attempt == 1
                    else "The previous generated test passed on the untouched repository. Generate a different test that directly reproduces the reported issue."
                )
                regression = await self._run_step(
                    run,
                    regression_step_key,
                    {"issue_id": issue.id, "attempt": regression_attempt, "feedback": feedback},
                    generate_regression_test(
                        issue.repository,
                        issue.number,
                        issue.title,
                        issue.body or "",
                        feedback,
                    ),
                    tokens=3072,
                )
                validation_step = await self.runtime.start_step(
                    run,
                    "regression_test_validation",
                    {"test_path": regression["test_path"], "attempt": regression_attempt},
                )
                await self.session.commit()
                before_result = await run_sandbox_validation(
                    repo_full_name=issue.repository,
                    file_rewrites={regression["test_path"]: regression["test_content"]},
                )
                await self.runtime.finish_step(validation_step, before_result)
                await self.session.commit()
                if not before_result.get("success") and self._has_test_failure(before_result):
                    break
            else:
                await self._fail(
                    run,
                    "Generated regression test did not fail after 3 attempts; manual issue verification is required",
                )
                return run
            await self._record_step_output(
                run, regression_step_key, {"generated": regression, "before": before_result}
            )

            await self.runtime.transition(run, "executing")
            analysis = await self._run_step(
                run,
                "patch_generation",
                {"issue_id": issue.id, "acceptance_criteria": acceptance.get("criteria", [])},
                analyze_issue(
                    issue.repository,
                    issue.number,
                    issue.title,
                    issue.body or "",
                    repository_memory,
                ),
                tokens=8192,
            )
            rewrites = analysis.get("file_rewrites") or {}
            if not rewrites:
                await self._fail(run, "Patch generation returned no file rewrites")
                return run
            rewrites = {
                **rewrites,
                regression["test_path"]: regression["test_content"],
            }
            self._validate_patch_budget(rewrites)

            await self.runtime.transition(run, "verifying")
            sandbox = await run_sandbox_validation_with_auto_heal(
                repo_full_name=issue.repository,
                title=issue.title,
                file_rewrites=rewrites,
            )
            await self._record_step_output(run, "sandbox_verification", sandbox)
            if sandbox.get("overall_status") != "passed":
                await self._fail(run, "Sandbox verification failed after healing attempts")
                return run

            await self.runtime.transition(run, "reviewing")
            review = await self._run_step(
                run,
                "independent_review",
                {"files": list(rewrites), "sandbox": sandbox},
                review_patch(
                    repo_full_name=issue.repository,
                    issue_title=issue.title,
                    issue_body=issue.body or "",
                    acceptance_criteria=acceptance.get("criteria", []),
                    file_rewrites=rewrites,
                    sandbox_result=sandbox,
                    repository_memory=repository_memory,
                ),
                tokens=4096,
            )
            if str(review.get("decision", "")).upper() != "PASS":
                await self._fail(run, f"Independent review decision: {review.get('decision', 'unknown')}")
                return run

            for finding in review.get("findings", []):
                self.session.add(
                    AgentReviewFinding(
                        run_id=run.id,
                        decision=str(review.get("decision", "PASS")),
                        summary=str(review.get("summary", "")),
                        severity=str(finding.get("severity", "low")),
                        file_path=str(finding.get("file_path", "")),
                        explanation=str(finding.get("explanation", "")),
                        suggested_fix=finding.get("suggested_fix"),
                    )
                )

            await remember(
                self.session,
                issue.repository,
                "review_pattern",
                f"Issue #{issue.number}: {review.get('summary', 'Independent review passed.')}",
                confidence=75,
                source="independent_review",
            )

            approval = await self.runtime.request_approval(
                run,
                "create_pull_request",
                "Sandbox passed and independent review approved the patch.",
            )
            await self._record_step_output(
                run,
                "awaiting_pr_approval",
                {
                    "approval_id": approval.id,
                    "issue_number": issue.number,
                    "analysis": analysis,
                    "acceptance": acceptance,
                    "sandbox": sandbox,
                    "review": review,
                },
            )
            await self.session.commit()
            return run
        except BudgetExceededError as error:
            await self._fail(run, str(error))
            return run
        except Exception as error:
            logger.exception("Contribution agent failed run=%s", run.id)
            await self._fail(run, str(error))
            return run

    async def approve_pr(self, run_id: int, reviewer: str) -> PullRequest:
        run = await self.session.get(AgentRun, run_id)
        if run is None:
            raise ValueError(f"Agent run not found: {run_id}")
        approval = await self.session.scalar(
            select(AgentApproval)
            .where(
                AgentApproval.run_id == run_id,
                AgentApproval.action == "create_pull_request",
                AgentApproval.status == "pending",
            )
            .order_by(AgentApproval.created_at.desc())
        )
        if approval is None:
            raise ValueError("No pending pull request approval")

        steps = (
            await self.session.scalars(
                select(AgentStep)
                .where(AgentStep.run_id == run_id, AgentStep.step_key == "awaiting_pr_approval")
                .order_by(AgentStep.id.desc())
            )
        ).first()
        if steps is None:
            raise ValueError("Patch checkpoint is missing")
        checkpoint = json.loads(steps.output_json)
        await self.runtime.decide_approval(
            approval, approved=True, reviewer=reviewer, reason="Approved for PR creation"
        )
        await self.runtime.transition(run, "executing")
        await self.session.commit()

        result = await create_pull_request(
            repo_full_name=run.repository,
            issue_number=checkpoint["issue_number"],
            pr_title=checkpoint["analysis"]["pr_title"],
            pr_body=checkpoint["analysis"]["pr_body"],
            file_rewrites=checkpoint["analysis"]["file_rewrites"],
        )
        pr = PullRequest(
            repository=run.repository,
            title=checkpoint["analysis"]["pr_title"],
            number=result.get("pr_number"),
            url=result.get("pr_url"),
            status="open",
            branch_name=result.get("branch"),
            issue_number=checkpoint["issue_number"],
            patch_content=json.dumps(checkpoint["analysis"]["file_rewrites"]),
            ai_summary=checkpoint["analysis"].get("analysis"),
            pr_body=checkpoint["analysis"]["pr_body"],
        )
        self.session.add(pr)
        await self.runtime.transition(run, "monitoring_ci")
        await self.session.commit()
        return pr

    @staticmethod
    def _has_test_failure(result: dict[str, Any]) -> bool:
        tests = result.get("checks", {}).get("tests", {})
        return tests.get("failed_count", 0) > 0 or tests.get("exit_code") not in (None, 0)

    @staticmethod
    def _validate_patch_budget(rewrites: dict[str, str]) -> None:
        if len(rewrites) > MAX_PATCH_FILES:
            raise ValueError(f"Patch changes {len(rewrites)} files; limit is {MAX_PATCH_FILES}")
        total_chars = sum(len(path) + len(content) for path, content in rewrites.items())
        if total_chars > MAX_PATCH_CHARS:
            raise ValueError(f"Patch is {total_chars} characters; limit is {MAX_PATCH_CHARS}")

    async def _run_step(self, run: AgentRun, key: str, input_data: dict[str, Any], operation: Any, tokens: int) -> dict[str, Any]:
        step = await self.runtime.start_step(run, key, input_data)
        await self.runtime.consume_model_budget(run, tokens=tokens)
        await self.session.commit()
        try:
            result = await operation
            await self.runtime.finish_step(step, result)
            await self.session.commit()
            return result
        except Exception as error:
            await self.runtime.fail_step(step, str(error))
            await self.session.commit()
            raise

    async def _record_step_output(self, run: AgentRun, key: str, output: dict[str, Any]) -> None:
        step = await self.session.scalar(
            select(AgentStep)
            .where(AgentStep.run_id == run.id, AgentStep.step_key == key)
            .order_by(AgentStep.id.desc())
        )
        if step is None:
            step = await self.runtime.start_step(run, key, {})
        await self.runtime.finish_step(step, output)
        await self.session.commit()

    async def _fail(self, run: AgentRun, reason: str) -> None:
        run.status = "failed"
        run.failure_reason = reason[:10_000]
        await self.session.commit()
