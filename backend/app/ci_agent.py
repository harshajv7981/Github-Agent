"""Approval-gated CI failure diagnosis and repair proposals."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runtime import AgentRuntime, Budget
from app.github_service import GitHubService
from app.models import AgentApproval, AgentRun, AgentStep, PullRequest
from app.sandbox_service import auto_heal_code


async def propose_ci_repair(session: AsyncSession, pull_request_id: int) -> dict[str, Any]:
    pull_request = await session.get(PullRequest, pull_request_id)
    if pull_request is None or not pull_request.number:
        raise ValueError("Tracked pull request or GitHub number not found")

    github = GitHubService()
    checks = await asyncio.to_thread(
        github.get_pull_request_checks, pull_request.repository, pull_request.number
    )
    if checks["failed_checks"] == 0:
        return {"status": "passing", "checks": checks}

    logs = await asyncio.to_thread(
        github.get_pull_request_failure_logs,
        pull_request.repository,
        pull_request.number,
    )
    try:
        rewrites = json.loads(pull_request.patch_content or "{}")
    except json.JSONDecodeError as error:
        raise ValueError("Stored pull request patch is not valid JSON") from error
    if not isinstance(rewrites, dict) or not rewrites:
        raise ValueError("Pull request has no stored rewrites to repair")

    run = AgentRuntime(session)
    agent_run = await run.create_run(
        idempotency_key=f"ci-repair:{pull_request_id}:{checks['commit_sha']}",
        repository=pull_request.repository,
        budget=Budget(max_model_requests=8, max_tokens=30_000, max_attempts=3),
    )
    if agent_run.status == "queued":
        await run.transition(agent_run, "planning")
        await run.transition(agent_run, "executing")

    diagnostics = {"checks": checks, "workflow_failures": logs["failures"]}
    step = await run.start_step(
        agent_run,
        "ci_repair_proposal",
        {"pull_request_id": pull_request_id, "commit_sha": checks["commit_sha"]},
    )
    await run.consume_model_budget(agent_run, tokens=8192)
    try:
        repair = await auto_heal_code(
            repo_full_name=pull_request.repository,
            feature_or_issue_title=f"CI repair for PR #{pull_request.number}",
            file_rewrites=rewrites,
            sandbox_diagnostics=diagnostics,
            max_attempts=agent_run.max_attempts,
        )
        await run.finish_step(step, repair)
        approval = await run.request_approval(
            agent_run,
            "push_ci_followup",
            "CI repair proposal generated; review the patch and sandbox result before pushing.",
        )
        await session.commit()
        return {
            "status": "approval_required",
            "run_id": agent_run.id,
            "approval_id": approval.id,
            "checks": checks,
            "proposal": repair,
        }
    except Exception as error:
        await run.fail_step(step, str(error))
        agent_run.status = "failed"
        agent_run.failure_reason = str(error)
        await session.commit()
        raise


async def approve_ci_repair(
    session: AsyncSession,
    pull_request_id: int,
    reviewer: str,
) -> dict[str, Any]:
    pull_request = await session.get(PullRequest, pull_request_id)
    if pull_request is None or not pull_request.number:
        raise ValueError("Tracked pull request or GitHub number not found")
    agent_run = await session.scalar(
        select(AgentRun)
        .where(AgentRun.idempotency_key.like(f"ci-repair:{pull_request_id}:%"))
        .order_by(AgentRun.id.desc())
    )
    if agent_run is None:
        raise ValueError("No CI repair proposal exists")
    approval = await session.scalar(
        select(AgentApproval)
        .where(
            AgentApproval.run_id == agent_run.id,
            AgentApproval.action == "push_ci_followup",
            AgentApproval.status == "pending",
        )
        .order_by(AgentApproval.id.desc())
    )
    if approval is None:
        raise ValueError("No pending CI repair approval exists")
    step = await session.scalar(
        select(AgentStep)
        .where(AgentStep.run_id == agent_run.id, AgentStep.step_key == "ci_repair_proposal")
        .order_by(AgentStep.id.desc())
    )
    if step is None:
        raise ValueError("CI repair proposal checkpoint is missing")
    proposal = json.loads(step.output_json or "{}")
    rewrites = proposal.get("file_rewrites") or {}
    if not rewrites:
        raise ValueError("CI repair proposal contains no file rewrites")

    result = await asyncio.to_thread(
        GitHubService().apply_pull_request_followup,
        pull_request.repository,
        pull_request.number,
        rewrites,
        f"Repair CI failures for PR #{pull_request.number}",
    )
    runtime = AgentRuntime(session)
    await runtime.decide_approval(
        approval, approved=True, reviewer=reviewer, reason="Approved CI follow-up commit"
    )
    await runtime.transition(agent_run, "monitoring_ci")
    pull_request.status = "open"
    await session.commit()
    return {"status": "committed", "run_id": agent_run.id, **result}
