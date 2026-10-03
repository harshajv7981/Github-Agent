import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.agent_runtime import (
    AgentRuntime,
    ApprovalRequiredError,
    BudgetExceededError,
    InvalidTransitionError,
    ToolRegistry,
    ToolSpec,
)
from app.contribution_agent import ContributionAgent


class AgentRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_state_machine_rejects_skipping_required_steps(self):
        runtime = AgentRuntime(AsyncMock())
        run = SimpleNamespace(status="queued", updated_at=None)

        with self.assertRaises(InvalidTransitionError):
            await runtime.transition(run, "executing")

        await runtime.transition(run, "planning")
        self.assertEqual(run.status, "planning")

    async def test_budget_is_enforced_before_model_call(self):
        runtime = AgentRuntime(AsyncMock())
        run = SimpleNamespace(
            model_requests=1,
            estimated_tokens=90,
            max_model_requests=2,
            max_tokens=100,
        )

        with self.assertRaises(BudgetExceededError):
            await runtime.consume_model_budget(run, requests=1, tokens=11)

        self.assertEqual(run.model_requests, 1)
        self.assertEqual(run.estimated_tokens, 90)

    async def test_tools_are_allow_listed_and_approval_gated(self):
        registry = ToolRegistry()
        registry.register(ToolSpec("safe", lambda args: {"value": args["value"]}, False))
        registry.register(ToolSpec("dangerous", lambda args: {"ok": True}, True))

        self.assertEqual(await registry.invoke("safe", {"value": 3}), {"value": 3})
        with self.assertRaises(ApprovalRequiredError):
            await registry.invoke("dangerous", {})
        self.assertEqual(await registry.invoke("dangerous", {}, approved=True), {"ok": True})

        with self.assertRaisesRegex(Exception, "allow-listed"):
            registry.get("unknown")

    def test_patch_budget_rejects_unbounded_rewrites(self):
        with self.assertRaisesRegex(ValueError, "files"):
            ContributionAgent._validate_patch_budget({f"file_{i}.py": "pass" for i in range(21)})


if __name__ == "__main__":
    unittest.main()
