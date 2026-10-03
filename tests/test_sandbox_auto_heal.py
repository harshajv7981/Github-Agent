import unittest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.sandbox_service import _run_terminal_check, run_sandbox_validation_with_auto_heal


class AutomaticSandboxHealingTests(unittest.IsolatedAsyncioTestCase):
    @patch("app.sandbox_service._run_cmd", return_value=(1, "output", "traceback", 0.2))
    def test_terminal_check_captures_failure_without_shell(self, run_command):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = _run_terminal_check(Path(temp_dir), ["python", "-m", "pytest", "tests"], 10, "process")

        self.assertFalse(result["passed"])
        self.assertEqual(result["exit_code"], 1)
        self.assertEqual(result["stderr"], "traceback")
        self.assertEqual(run_command.call_args.args[0][1:], ["-m", "pytest", "tests"])

    def test_terminal_check_rejects_shell_commands(self):
        with self.assertRaises(ValueError):
            _run_terminal_check(Path(tempfile.gettempdir()), ["sh", "-c", "rm -rf /"], 10, "process")

    async def test_clean_validation_skips_healing(self):
        clean_report = {"overall_status": "passed", "success": True}
        with (
            patch(
                "app.sandbox_service.run_sandbox_validation",
                new=AsyncMock(return_value=clean_report),
            ),
            patch("app.sandbox_service.auto_heal_code", new=AsyncMock()) as heal,
        ):
            result = await run_sandbox_validation_with_auto_heal(
                "owner/repo", "Fix issue", {"src.py": "pass"}, "process"
            )

        self.assertEqual(result, clean_report)
        heal.assert_not_awaited()

    async def test_failed_validation_returns_final_repair_and_history(self):
        initial_report = {"overall_status": "failed", "summary": "syntax failed"}
        final_report = {"overall_status": "passed", "summary": "all checks passed"}
        healed_rewrites = {"src.py": "fixed"}
        healing = {
            "file_rewrites": healed_rewrites,
            "healing_analysis": "Fixed the syntax error.",
            "healed": True,
            "attempts_used": 1,
            "diff_history": [{"attempt": 1, "passed": True}],
            "sandbox_result": final_report,
        }
        with (
            patch(
                "app.sandbox_service.run_sandbox_validation",
                new=AsyncMock(return_value=initial_report),
            ),
            patch(
                "app.sandbox_service.auto_heal_code",
                new=AsyncMock(return_value=healing),
            ) as heal,
        ):
            result = await run_sandbox_validation_with_auto_heal(
                "owner/repo", "Fix issue", {"src.py": "broken"}, "process"
            )

        self.assertEqual(result["overall_status"], "passed")
        self.assertEqual(result["file_rewrites"], healed_rewrites)
        self.assertTrue(result["healed"])
        self.assertEqual(result["healing_attempts"], 1)
        self.assertEqual(result["healing_history"], healing["diff_history"])
        self.assertEqual(heal.await_args.kwargs["runtime"], "process")

    async def test_ai_failure_preserves_original_sandbox_report(self):
        initial_report = {"overall_status": "failed", "summary": "tests failed"}
        with (
            patch(
                "app.sandbox_service.run_sandbox_validation",
                new=AsyncMock(return_value=initial_report),
            ),
            patch(
                "app.sandbox_service.auto_heal_code",
                new=AsyncMock(side_effect=RuntimeError("provider unavailable")),
            ),
        ):
            result = await run_sandbox_validation_with_auto_heal(
                "owner/repo", "Fix issue", {"src.py": "broken"}, "process"
            )

        self.assertEqual(result["overall_status"], "failed")
        self.assertEqual(result["summary"], "tests failed")
        self.assertFalse(result["healed"])
        self.assertEqual(result["file_rewrites"], {"src.py": "broken"})


if __name__ == "__main__":
    unittest.main()