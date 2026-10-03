"""Durable runtime primitives for resumable, approval-gated agent runs."""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentApproval, AgentRun, AgentStep, AgentToolCall


RUN_STATES = (
    "queued",
    "planning",
    "awaiting_approval",
    "executing",
    "verifying",
    "reviewing",
    "awaiting_pr_approval",
    "monitoring_ci",
    "completed",
    "failed",
    "cancelled",
)

_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "queued": {"planning", "cancelled"},
    "planning": {"awaiting_approval", "executing", "failed", "cancelled"},
    "awaiting_approval": {"executing", "cancelled", "failed"},
    "executing": {"verifying", "awaiting_approval", "failed", "cancelled"},
    "verifying": {"reviewing", "executing", "failed", "cancelled"},
    "reviewing": {"awaiting_pr_approval", "executing", "failed", "cancelled"},
    "awaiting_pr_approval": {"monitoring_ci", "cancelled", "failed"},
    "monitoring_ci": {"completed", "executing", "failed", "cancelled"},
    "completed": set(),
    "failed": {"planning", "cancelled"},
    "cancelled": set(),
}


class AgentRuntimeError(RuntimeError):
    """Base error for invalid or unsafe agent runtime operations."""


class InvalidTransitionError(AgentRuntimeError):
    pass


class BudgetExceededError(AgentRuntimeError):
    pass


class ApprovalRequiredError(AgentRuntimeError):
    pass


@dataclass(frozen=True)
class Budget:
    max_model_requests: int = 30
    max_tokens: int = 100_000
    max_attempts: int = 3


@dataclass(frozen=True)
class ToolSpec:
    name: str
    handler: Callable[[dict[str, Any]], Any]
    requires_approval: bool = True


class ToolRegistry:
    """Allow-list of agent tools; unknown tools can never execute."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if not spec.name or spec.name.startswith("_"):
            raise ValueError("Tool names must be public and non-empty")
        if spec.name in self._tools:
            raise ValueError(f"Tool already registered: {spec.name}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as error:
            raise AgentRuntimeError(f"Tool is not allow-listed: {name}") from error

    async def invoke(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        approved: bool = False,
    ) -> Any:
        spec = self.get(name)
        if spec.requires_approval and not approved:
            raise ApprovalRequiredError(f"Tool requires approval: {name}")
        result = spec.handler(arguments)
        if inspect.isawaitable(result):
            result = await result
        return result


class AgentRuntime:
    """Persistence-backed state machine and budget/approval coordinator."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_run(
        self,
        *,
        idempotency_key: str,
        issue_id: int | None = None,
        repository: str | None = None,
        budget: Budget = Budget(),
    ) -> AgentRun:
        existing = await self.session.scalar(
            select(AgentRun).where(AgentRun.idempotency_key == idempotency_key)
        )
        if existing:
            return existing
        run = AgentRun(
            idempotency_key=idempotency_key,
            issue_id=issue_id,
            repository=repository,
            max_attempts=budget.max_attempts,
            max_model_requests=budget.max_model_requests,
            max_tokens=budget.max_tokens,
        )
        self.session.add(run)
        await self.session.flush()
        return run

    async def transition(self, run: AgentRun, state: str) -> AgentRun:
        if state not in RUN_STATES:
            raise InvalidTransitionError(f"Unknown agent state: {state}")
        if state == run.status:
            return run
        if state not in _ALLOWED_TRANSITIONS.get(run.status, set()):
            raise InvalidTransitionError(f"Cannot transition {run.status} -> {state}")
        run.status = state
        run.updated_at = datetime.utcnow()
        await self.session.flush()
        return run

    async def start_step(
        self,
        run: AgentRun,
        step_key: str,
        input_data: dict[str, Any],
    ) -> AgentStep:
        step = AgentStep(
            run_id=run.id,
            step_key=step_key,
            status="running",
            attempt=run.attempt + 1,
            input_json=json.dumps(input_data, sort_keys=True),
            started_at=datetime.utcnow(),
        )
        run.current_step = step_key
        run.attempt += 1
        self.session.add(step)
        await self.session.flush()
        return step

    async def finish_step(
        self,
        step: AgentStep,
        output_data: dict[str, Any],
    ) -> None:
        step.status = "completed"
        step.output_json = json.dumps(output_data, sort_keys=True)
        step.completed_at = datetime.utcnow()
        await self.session.flush()

    async def fail_step(self, step: AgentStep, error: str) -> None:
        step.status = "failed"
        step.error = error[:10_000]
        step.completed_at = datetime.utcnow()
        await self.session.flush()

    async def consume_model_budget(
        self,
        run: AgentRun,
        *,
        requests: int = 1,
        tokens: int = 0,
    ) -> None:
        if requests < 0 or tokens < 0:
            raise ValueError("Budget consumption cannot be negative")
        if run.model_requests + requests > run.max_model_requests:
            raise BudgetExceededError("Model request budget exceeded")
        if run.estimated_tokens + tokens > run.max_tokens:
            raise BudgetExceededError("Token budget exceeded")
        run.model_requests += requests
        run.estimated_tokens += tokens
        await self.session.flush()

    async def request_approval(self, run: AgentRun, action: str, reason: str) -> AgentApproval:
        approval = AgentApproval(run_id=run.id, action=action, reason=reason)
        self.session.add(approval)
        await self.transition(run, "awaiting_approval")
        await self.session.flush()
        return approval

    async def decide_approval(
        self,
        approval: AgentApproval,
        *,
        approved: bool,
        reviewer: str,
        reason: str | None = None,
    ) -> None:
        approval.status = "approved" if approved else "rejected"
        approval.reviewer = reviewer
        approval.reason = reason or approval.reason
        approval.decided_at = datetime.utcnow()
        await self.session.flush()

    async def record_tool_call(
        self,
        run: AgentRun,
        spec: ToolSpec,
        arguments: dict[str, Any],
    ) -> AgentToolCall:
        call = AgentToolCall(
            run_id=run.id,
            tool_name=spec.name,
            input_json=json.dumps(arguments, sort_keys=True),
            requires_approval=spec.requires_approval,
        )
        self.session.add(call)
        await self.session.flush()
        return call

    async def execute_tool(
        self,
        run: AgentRun,
        registry: ToolRegistry,
        name: str,
        arguments: dict[str, Any],
        *,
        approved: bool = False,
    ) -> Any:
        spec = registry.get(name)
        call = await self.record_tool_call(run, spec, arguments)
        if spec.requires_approval and not approved:
            call.status = "awaiting_approval"
            await self.session.flush()
            raise ApprovalRequiredError(f"Tool requires approval: {name}")
        call.status = "running"
        try:
            result = await registry.invoke(name, arguments, approved=approved)
            call.status = "completed"
            call.output_json = json.dumps(result, sort_keys=True, default=str)
            call.approved_at = datetime.utcnow() if approved else None
            await self.session.flush()
            return result
        except Exception as error:
            call.status = "failed"
            call.error = str(error)[:10_000]
            await self.session.flush()
            raise
