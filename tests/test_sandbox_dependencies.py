import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.sandbox_service import (
    _prepare_test_environment,
    _recover_sandbox_dependencies,
    _run_pytest_suite,
    _safe_rewrite_content,
)


class SandboxDependencyTests(unittest.IsolatedAsyncioTestCase):
    @patch("app.sandbox_service._prepare_test_environment", return_value=("python", "test", None))
    @patch(
        "app.sandbox_service._run_cmd",
        return_value=(4, "", "ImportError while loading conftest: ModuleNotFoundError", 0.2),
    )
    def test_pytest_startup_import_error_is_not_reported_as_pass(self, run_command, prepare_env):
        with tempfile.TemporaryDirectory() as temp_dir:
            sandbox_dir = Path(temp_dir)
            python_path = sandbox_dir / "bin" / "python"
            python_path.parent.mkdir()
            python_path.touch()
            (sandbox_dir / "test").mkdir()

            result = _run_pytest_suite(sandbox_dir, [], runtime="process")

            self.assertFalse(result["passed"])
            self.assertEqual(result["tests_run"], 0)
            self.assertEqual(result["error_count"], 1)
            self.assertIn("failed before collecting", result["summary"])

    @patch("app.sandbox_service._run_cmd", return_value=(0, "", "", 0.1))
    @patch("app.sandbox_service.shutil.which", side_effect=lambda name: f"/bin/{name}")
    def test_uses_locked_uv_project(self, which, run_command):
        with tempfile.TemporaryDirectory() as temp_dir:
            sandbox_dir = Path(temp_dir)
            (sandbox_dir / "pyproject.toml").write_text("[project]\nname='sample'\n")
            (sandbox_dir / "uv.lock").write_text("version = 1\n")

            python_path, manager, error = _prepare_test_environment(sandbox_dir, "process")

            self.assertIsNone(error)
            self.assertEqual(manager, "uv")
            self.assertTrue(python_path.endswith(".patchwork-venv/bin/python"))
            self.assertIn("--locked", run_command.call_args_list[0].args[0])
            self.assertEqual(len(run_command.call_args_list), 2)
            self.assertEqual(
                run_command.call_args_list[1].args[0],
                ["/bin/uv", "pip", "install", "--python", python_path, "pytest"],
            )

    async def test_llm_dependency_plan_installs_only_validated_packages(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            sandbox_dir = Path(temp_dir)
            python_path = sandbox_dir / "bin" / "python"
            python_path.parent.mkdir()
            python_path.touch()
            llm = SimpleNamespace(
                generate=AsyncMock(
                    return_value=SimpleNamespace(
                        response='{"packages": ["rich", "pytest-asyncio"], "reasoning": "imports"}'
                    )
                )
            )
            with (
                patch("app.sandbox_service.get_llm_client", return_value=llm),
                patch(
                    "app.sandbox_service._run_cmd",
                    return_value=(0, "", "", 0.1),
                ) as run_command,
            ):
                result = await _recover_sandbox_dependencies(
                    sandbox_dir,
                    str(python_path),
                    "ModuleNotFoundError: No module named 'rich'",
                    "process",
                )

        self.assertTrue(result["recovered"])
        install_command = run_command.call_args.args[0]
        self.assertEqual(
            install_command[-2:],
            ["rich", "pytest-asyncio"],
        )

    async def test_rejects_llm_shell_command_in_dependency_plan(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            python_path = Path(temp_dir) / "bin" / "python"
            python_path.parent.mkdir()
            python_path.touch()
            llm = SimpleNamespace(
                generate=AsyncMock(
                    return_value=SimpleNamespace(
                        response='{"packages": ["rich; rm -rf /"], "reasoning": "bad"}'
                    )
                )
            )
            with patch("app.sandbox_service.get_llm_client", return_value=llm):
                result = await _recover_sandbox_dependencies(
                    Path(temp_dir),
                    str(python_path),
                    "missing dependency",
                    "process",
                )

        self.assertFalse(result["recovered"])
        self.assertIn("invalid package", result["reason"])

    def test_preserves_original_manifest_when_rewrite_contains_file_marker(self):
        original = "rich\npytest\n"
        result = _safe_rewrite_content(
            "requirements.txt",
            "rich\n=== END FILE ===\n",
            original,
        )

        self.assertEqual(result, original)

    @patch("app.sandbox_service._run_cmd", return_value=(0, "", "", 0.1))
    @patch("app.sandbox_service.shutil.which", side_effect=lambda name: f"/bin/{name}")
    def test_uses_poetry_project_and_non_optional_groups(self, which, run_command):
        with tempfile.TemporaryDirectory() as temp_dir:
            sandbox_dir = Path(temp_dir)
            (sandbox_dir / "pyproject.toml").write_text(
                "[tool.poetry]\nname='sample'\nversion='0.1.0'\n"
            )
            (sandbox_dir / "poetry.lock").write_text("# lock\n")

            python_path, manager, error = _prepare_test_environment(sandbox_dir, "process")

            self.assertIsNone(error)
            self.assertEqual(manager, "Poetry")
            self.assertTrue(python_path.endswith(".venv/bin/python"))
            poetry_command = run_command.call_args_list[0].args[0]
            self.assertIn("--no-root", poetry_command)
            self.assertIn("--all-groups", poetry_command)
            self.assertEqual(len(run_command.call_args_list), 2)

    @patch("app.sandbox_service._run_cmd", return_value=(0, "", "", 0.1))
    @patch("app.sandbox_service.shutil.which", side_effect=lambda name: f"/bin/{name}")
    def test_installs_root_and_test_requirements_before_unlocked_uv(self, which, run_command):
        with tempfile.TemporaryDirectory() as temp_dir:
            sandbox_dir = Path(temp_dir)
            (sandbox_dir / "pyproject.toml").write_text("[project]\nname='sample'\n")
            (sandbox_dir / "requirements.txt").write_text("numpy\n")
            (sandbox_dir / "test").mkdir()
            (sandbox_dir / "test" / "requirements.txt").write_text("gradio\n")

            python_path, manager, error = _prepare_test_environment(sandbox_dir, "process")

            self.assertIsNone(error)
            self.assertEqual(manager, "pip requirements")
            self.assertEqual(
                python_path,
                str(sandbox_dir / ".patchwork-venv" / "bin" / "python"),
            )
            install_command = run_command.call_args_list[1].args[0]
            self.assertIn("pytest", install_command)
            self.assertIn("requirements.txt", install_command)
            self.assertIn("test/requirements.txt", install_command)

    @patch(
        "app.sandbox_service._run_cmd",
        side_effect=[(0, "", "", 0.1), (1, "", "resolver failed", 0.2)],
    )
    def test_reports_dependency_install_failure(self, run_command):
        with tempfile.TemporaryDirectory() as temp_dir:
            sandbox_dir = Path(temp_dir)
            (sandbox_dir / "requirements.txt").write_text("missing-package\n")

            _, manager, error = _prepare_test_environment(sandbox_dir, "process")

            self.assertEqual(manager, "pip requirements")
            self.assertIn("Dependency installation", error)
            self.assertIn("resolver failed", error)

    @patch("app.sandbox_service._run_cmd", return_value=(0, "", "", 0.1))
    @patch("app.sandbox_service.shutil.which", side_effect=lambda name: f"/bin/{name}")
    def test_discovers_nested_package_requirements_and_dev_extra(self, which, run_command):
        with tempfile.TemporaryDirectory() as temp_dir:
            sandbox_dir = Path(temp_dir)
            package_dir = sandbox_dir / "libs" / "agno"
            package_dir.mkdir(parents=True)
            (package_dir / "pyproject.toml").write_text(
                "[project]\nname='agno'\n"
                "[project.optional-dependencies]\n"
                "dev=['pytest']\n"
            )
            (package_dir / "requirements.txt").write_text("rich\n")
            (package_dir / "tests").mkdir()

            python_path, manager, error = _prepare_test_environment(sandbox_dir, "process")

            self.assertIsNone(error)
            self.assertEqual(manager, "pip requirements")
            install_command = run_command.call_args_list[1].args[0]
            self.assertIn("libs/agno[dev]", install_command)

    @patch("app.sandbox_service._run_cmd", return_value=(0, "", "", 0.1))
    @patch("app.sandbox_service.shutil.which", return_value=None)
    def test_uses_pip_for_unlocked_pyproject_without_uv_or_poetry(self, which, run_command):
        with tempfile.TemporaryDirectory() as temp_dir:
            sandbox_dir = Path(temp_dir)
            (sandbox_dir / "pyproject.toml").write_text(
                "[project]\nname='sample'\nversion='0.1.0'\n"
                "[project.optional-dependencies]\n"
                "dev=['pytest']\n"
            )

            python_path, manager, error = _prepare_test_environment(sandbox_dir, "process")

            self.assertIsNone(error)
            self.assertEqual(manager, "pip pyproject")
            self.assertTrue(python_path.endswith(".patchwork-venv/bin/python"))
            self.assertIn("-e", run_command.call_args_list[1].args[0])
            self.assertIn(".[dev]", run_command.call_args_list[1].args[0])


if __name__ == "__main__":
    unittest.main()