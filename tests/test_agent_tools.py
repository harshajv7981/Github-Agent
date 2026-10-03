import tempfile
import unittest
from pathlib import Path

from app.agent_runtime import ApprovalRequiredError
from app.agent_tools import build_repository_tool_registry


class AgentToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_and_search_tools_stay_inside_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src.py").write_text("def target():\n    return 1\n")
            registry = build_repository_tool_registry()

            result = await registry.invoke(
                "search_repository",
                {"repository_root": str(root), "query": "target"},
            )
            self.assertEqual(result["matches"][0]["path"], "src.py")

            with self.assertRaises(ValueError):
                await registry.invoke(
                    "read_repository_file",
                    {"repository_root": str(root), "path": "../secret"},
                )

    async def test_test_execution_requires_approval(self):
        registry = build_repository_tool_registry()
        with self.assertRaises(ApprovalRequiredError):
            await registry.invoke(
                "run_repository_tests",
                {"repository_root": tempfile.gettempdir(), "command": ["python", "-V"]},
            )


if __name__ == "__main__":
    unittest.main()
