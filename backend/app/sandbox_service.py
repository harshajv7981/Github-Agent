"""
Sandbox Service: Isolated environment execution for pytest, linters (flake8/ruff),
and type checkers (mypy) with automatic error diagnostics and AI self-healing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from app.llm_client import get_llm_client
from app.model_router import model_for

load_dotenv()

logger = logging.getLogger(__name__)

REPOS_CACHE_DIR = Path.home() / ".patchwork" / "repos"
SANDBOX_RUNTIME = os.getenv("SANDBOX_RUNTIME", "process").lower()
SANDBOX_DOCKER_IMAGE = os.getenv("SANDBOX_DOCKER_IMAGE", "patchwork-sandbox:latest")

# Python executable from virtual environment
VENV_PYTHON = sys.executable


def _clone_or_get_repo(repo_full_name: str) -> Path:
    """Ensure repository is cloned in local cache and return path."""
    REPOS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    slug = repo_full_name.replace("/", "__")
    dest = REPOS_CACHE_DIR / slug

    if not dest.exists():
        url = f"https://github.com/{repo_full_name}.git"
        subprocess.run(
            ["git", "clone", "--depth", "1", url, str(dest)],
            check=True,
            capture_output=True,
            text=True,
        )
    return dest


SENSITIVE_ENV_KEYS = {
    "GITHUB_TOKEN", "GH_TOKEN", "GITHUB_PAT",
    "DATABASE_URL", "DB_URL", "DB_PASSWORD",
    "SECRET_KEY", "API_KEY", "AWS_SECRET_ACCESS_KEY",
    "AWS_ACCESS_KEY_ID", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
}
SANDBOX_ENV_KEYS = {"VIRTUAL_ENV", "CONDA_PREFIX", "CONDA_DEFAULT_ENV"}

MAX_SANDBOX_MEMORY_MB = 512
MAX_SANDBOX_OUTPUT_BYTES = 1_000_000
SANDBOX_DEPENDENCY_TIMEOUT_SECONDS = 180
MAX_HEAL_ATTEMPTS: int | None = 10
TERMINAL_COMMANDS = {"python", "python3", "pytest", "node", "npm", "npx", "go", "cargo", "make"}


class DependencyInstallPlan(BaseModel):
    packages: list[str] = Field(default_factory=list, max_length=32)
    reasoning: str = ""


PACKAGE_SPEC_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[A-Za-z0-9_.-]+(?:,[A-Za-z0-9_.-]+)*\])?(?:[<>=!~]=?[A-Za-z0-9.*+!<>=~.-]+(?:,[<>=!~]=?[A-Za-z0-9.*+!<>=~.-]+)*)?$"
)


def _make_sandbox_env(cwd: Path, env_extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {}
    for k, v in os.environ.items():
        if k.upper() in SENSITIVE_ENV_KEYS or k.upper() in SANDBOX_ENV_KEYS:
            continue
        if any(pat in k.upper() for pat in ("TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")):
            continue
        env[k] = v
    env["PYTHONPATH"] = str(cwd)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if env_extra:
        env.update(env_extra)
    return env


def _safe_sandbox_path(root: Path, rel_path: str) -> Path:
    candidate = Path(rel_path.strip())
    if candidate.is_absolute():
        raise ValueError(f"Absolute rewrite paths are not allowed: {rel_path}")

    root_resolved = root.resolve()
    path_resolved = (root_resolved / candidate).resolve()
    try:
        path_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"Rewrite path escapes repository: {rel_path}") from exc
    return path_resolved


def _is_dependency_manifest(path: str) -> bool:
    name = Path(path).name.lower()
    return name.startswith("requirements") and name.endswith(".txt") or name in {
        "pyproject.toml", "setup.cfg", "tox.ini", "pytest.ini"
    }


def _safe_rewrite_content(path: str, content: str, original: str | None = None) -> str:
    if "=== FILE:" in content or "=== END FILE ===" in content:
        if _is_dependency_manifest(path) and original is not None:
            logger.warning("Ignoring malformed dependency manifest rewrite path=%s", path)
            return original
        raise ValueError(f"Malformed file markers in rewrite: {path}")
    return content


def _run_cmd(
    cmd: list[str],
    cwd: Path,
    timeout: int = 30,
    env_extra: dict[str, str] | None = None,
    runtime: str | None = None,
) -> tuple[int, str, str, float]:
    """Execute command with timeout and return (exit_code, stdout, stderr, duration)."""
    runtime = (runtime or SANDBOX_RUNTIME).lower()
    env = _make_sandbox_env(cwd, env_extra)

    if runtime not in {"process", "docker"}:
        return 1, "", f"Unsupported sandbox runtime: {runtime}", 0.0

    if runtime == "docker":
        executable = "python" if Path(cmd[0]).name.startswith("python") else cmd[0]
        cmd = [executable, *cmd[1:]]
        full_cmd = [
            "docker", "run", "--rm",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt", "no-new-privileges",
            "--pids-limit", "128",
            "--memory", f"{MAX_SANDBOX_MEMORY_MB}m",
            "--cpus", "1",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
            "-v", f"{cwd.resolve()}:/workspace:rw",
            "-w", "/workspace",
            "-e", "PYTHONPATH=/workspace",
            "-e", "PYTHONDONTWRITEBYTECODE=1",
            SANDBOX_DOCKER_IMAGE,
            *cmd,
        ]
    else:
        full_cmd = cmd

    resource_prefix: list[str] = []
    if runtime == "process" and sys.platform != "win32" and shutil.which("ulimit") is not None:
        pass
    if runtime == "process" and (sys.platform == "darwin" or sys.platform.startswith("linux")):
        mem_kb = MAX_SANDBOX_MEMORY_MB * 1024
        resource_prefix = ["bash", "-c",
            f"ulimit -v {mem_kb} 2>/dev/null; exec \"$@\"", "--"] if shutil.which("bash") else []

    full_cmd = resource_prefix + full_cmd if resource_prefix else full_cmd

    t0 = time.time()
    try:
        proc = subprocess.run(
            full_cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        stdout = proc.stdout[:MAX_SANDBOX_OUTPUT_BYTES] if proc.stdout else ""
        stderr = proc.stderr[:MAX_SANDBOX_OUTPUT_BYTES] if proc.stderr else ""
        duration = round(time.time() - t0, 3)
        return proc.returncode, stdout, stderr, duration
    except subprocess.TimeoutExpired as e:
        duration = round(time.time() - t0, 3)
        return -1, "", f"Execution timed out after {timeout} seconds", duration
    except Exception as e:
        duration = round(time.time() - t0, 3)
        return 1, "", str(e), duration


def _check_syntax(sandbox_dir: Path, target_files: list[str], runtime: str) -> dict[str, Any]:
    """Compile changed python files with py_compile to detect syntax errors."""
    errors = []
    checked = []

    for rel_path in target_files:
        if not rel_path.endswith(".py"):
            continue
        file_path = sandbox_dir / rel_path
        if not file_path.exists():
            continue

        checked.append(rel_path)
        compile_path = rel_path if runtime == "docker" else str(file_path)
        code, out, err, _ = _run_cmd(
            [VENV_PYTHON, "-m", "py_compile", compile_path],
            cwd=sandbox_dir,
            timeout=10,
            runtime=runtime,
        )
        if code != 0:
            errors.append({
                "file": rel_path,
                "message": (err or out).strip(),
            })

    passed = len(errors) == 0
    return {
        "passed": passed,
        "checked_files": checked,
        "errors": errors,
        "summary": "All syntax checks passed" if passed else f"{len(errors)} syntax error(s) found",
    }


def _check_linters(sandbox_dir: Path, target_files: list[str], runtime: str) -> dict[str, Any]:
    """Run flake8 and ruff on modified files."""
    py_files = [f for f in target_files if f.endswith(".py") and (sandbox_dir / f).exists()]
    if not py_files:
        return {
            "passed": True,
            "tool": "flake8",
            "warnings_count": 0,
            "warnings": [],
            "summary": "No Python files to lint",
        }

    warnings = []
    # Run flake8 with standard relaxed parameters
    cmd = [
        VENV_PYTHON, "-m", "flake8",
        "--max-line-length=120",
        "--ignore=E501,W503,E203",
        *py_files
    ]
    code, out, err, _ = _run_cmd(cmd, cwd=sandbox_dir, timeout=15, runtime=runtime)

    if out.strip():
        for line in out.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            # Format: filename:line:col: code message
            parts = line.split(":", 3)
            if len(parts) >= 4:
                warnings.append({
                    "file": Path(parts[0].strip()).name,
                    "line": parts[1].strip(),
                    "col": parts[2].strip(),
                    "message": parts[3].strip(),
                })
            else:
                warnings.append({
                    "file": "general",
                    "line": "-",
                    "col": "-",
                    "message": line,
                })

    passed = len(warnings) == 0
    return {
        "passed": passed,
        "tool": "flake8",
        "warnings_count": len(warnings),
        "warnings": warnings[:20],  # cap at 20 warnings
        "summary": "0 lint violations" if passed else f"{len(warnings)} lint warning(s)",
    }


def _check_types(sandbox_dir: Path, target_files: list[str], runtime: str) -> dict[str, Any]:
    """Run mypy on modified files."""
    py_files = [f for f in target_files if f.endswith(".py") and (sandbox_dir / f).exists()]
    if not py_files:
        return {
            "passed": True,
            "tool": "mypy",
            "errors": [],
            "summary": "No Python files for type checking",
        }

    cmd = [
        VENV_PYTHON, "-m", "mypy",
        "--ignore-missing-imports",
        "--no-error-summary",
        "--hide-error-codes",
        *py_files
    ]
    code, out, err, _ = _run_cmd(cmd, cwd=sandbox_dir, timeout=20, runtime=runtime)

    type_errors = []
    if out.strip():
        for line in out.strip().split("\n"):
            line = line.strip()
            if "error:" in line.lower():
                type_errors.append(line)

    passed = len(type_errors) == 0
    return {
        "passed": passed,
        "tool": "mypy",
        "errors_count": len(type_errors),
        "errors": type_errors[:15],
        "summary": "Strict type check passed" if passed else f"{len(type_errors)} type issue(s) detected",
    }


def _prepare_test_environment(
    sandbox_dir: Path,
    runtime: str,
) -> tuple[str, str, str | None]:
    """Install declared test dependencies into an isolated per-run environment."""
    pyproject = sandbox_dir / "pyproject.toml"
    uv_lock = sandbox_dir / "uv.lock"
    poetry_lock = sandbox_dir / "poetry.lock"
    poetry_project = pyproject.is_file() and re.search(
        r"(?m)^\s*\[tool\.poetry\]\s*$",
        pyproject.read_text(encoding="utf-8", errors="replace"),
    ) is not None
    requirement_files = [
        sandbox_dir / name
        for name in (
            "requirements.txt",
            "requirements-dev.txt",
            "requirements-test.txt",
            "test-requirements.txt",
        )
        if (sandbox_dir / name).is_file()
    ]
    requirement_files.extend(
        path
        for path in (sandbox_dir / "test" / "requirements.txt", sandbox_dir / "tests" / "requirements.txt")
        if path.is_file()
    )

    editable_projects: list[Path] = []
    if not pyproject.is_file() and not requirement_files:
        for nested_pyproject in sandbox_dir.glob("**/pyproject.toml"):
            package_dir = nested_pyproject.parent
            if len(package_dir.relative_to(sandbox_dir).parts) > 3:
                continue
            if any((package_dir / name).is_dir() for name in ("test", "tests", "testing")):
                editable_projects.append(package_dir)
        for nested_requirements in sandbox_dir.glob("**/requirements*.txt"):
            if len(nested_requirements.relative_to(sandbox_dir).parts) > 3:
                continue
            if nested_requirements not in requirement_files:
                requirement_files.append(nested_requirements)

        if editable_projects:
            requirement_files = []

    if not pyproject.is_file() and not requirement_files and not editable_projects:
        return VENV_PYTHON, "Patchwork environment", None

    if runtime == "docker":
        return (
            VENV_PYTHON,
            "Docker image",
            "Dependency installation is disabled in Docker sandbox mode because its network is disabled; "
            "add the target project's dependencies to the sandbox image.",
        )

    uv = shutil.which("uv")
    poetry = shutil.which("poetry")
    poetry_project_config = poetry_lock.is_file() or poetry_project
    if pyproject.is_file() and uv_lock.is_file() and uv:
        manager = "uv"
        environment_dir = sandbox_dir / ".patchwork-venv"
        command = [uv, "sync", "--all-groups", "--no-install-project"]
        command.append("--locked")
        env_extra = {"UV_PROJECT_ENVIRONMENT": str(environment_dir)}
        python_path = environment_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    elif pyproject.is_file() and poetry_project_config and poetry:
        manager = "Poetry"
        command = [poetry, "install", "--no-interaction", "--no-root", "--all-groups"]
        env_extra = {"POETRY_VIRTUALENVS_IN_PROJECT": "true"}
        python_path = sandbox_dir / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    elif pyproject.is_file() and poetry_project_config and not requirement_files:
        return VENV_PYTHON, "Poetry", "Poetry project detected but the poetry executable is unavailable."
    elif requirement_files or editable_projects:
        manager = "pip requirements"
        environment_dir = sandbox_dir / ".patchwork-venv"
        python_path = environment_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        code, out, err, _ = _run_cmd(
            [VENV_PYTHON, "-m", "venv", str(environment_dir)],
            cwd=sandbox_dir,
            timeout=60,
            runtime=runtime,
        )
        if code != 0:
            return VENV_PYTHON, manager, f"Could not create test environment:\n{(out + err)[-3000:]}"
        command = [str(python_path), "-m", "pip", "install", "--disable-pip-version-check", "pytest"]
        for project_dir in editable_projects:
            command.extend(["-e", f"{project_dir.relative_to(sandbox_dir)}[dev]"])
        if not editable_projects:
            for requirement_file in requirement_files:
                command.extend(["-r", str(requirement_file.relative_to(sandbox_dir))])
        env_extra = {}
    elif pyproject.is_file() and uv and not poetry_project_config:
        manager = "uv"
        environment_dir = sandbox_dir / ".patchwork-venv"
        command = [uv, "sync", "--all-groups", "--no-install-project"]
        env_extra = {"UV_PROJECT_ENVIRONMENT": str(environment_dir)}
        python_path = environment_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    elif pyproject.is_file() and not poetry_project_config:
        manager = "pip pyproject"
        environment_dir = sandbox_dir / ".patchwork-venv"
        python_path = environment_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        code, out, err, _ = _run_cmd(
            [VENV_PYTHON, "-m", "venv", str(environment_dir)],
            cwd=sandbox_dir,
            timeout=60,
            runtime=runtime,
        )
        if code != 0:
            return VENV_PYTHON, manager, f"Could not create test environment:\n{(out + err)[-3000:]}"
        command = [str(python_path), "-m", "pip", "install", "--disable-pip-version-check", "-e", ".[dev]"]
        env_extra = {}
    else:
        return VENV_PYTHON, "project manifest", "A pyproject.toml was found, but no supported uv or Poetry setup is available."

    logger.info("Installing sandbox test dependencies manager=%s", manager)
    code, out, err, duration = _run_cmd(
        command,
        cwd=sandbox_dir,
        timeout=SANDBOX_DEPENDENCY_TIMEOUT_SECONDS,
        env_extra=env_extra,
        runtime=runtime,
    )
    if code != 0:
        detail = (err or out or f"installer exited with status {code}").strip()
        logger.warning("Sandbox dependency installation failed manager=%s duration_seconds=%.2f", manager, duration)
        return str(python_path), manager, f"Dependency installation with {manager} failed:\n{detail[-3000:]}"

    if manager == "uv":
        pytest_command = [uv, "pip", "install", "--python", str(python_path), "pytest"]
    elif manager != "pip requirements":
        pytest_command = [str(python_path), "-m", "pip", "install", "--disable-pip-version-check", "pytest"]
    else:
        pytest_command = None

    if pytest_command:
        code, out, err, pytest_duration = _run_cmd(
            pytest_command,
            cwd=sandbox_dir,
            timeout=SANDBOX_DEPENDENCY_TIMEOUT_SECONDS,
            runtime=runtime,
        )
        duration += pytest_duration
        if code != 0:
            detail = (err or out or f"installer exited with status {code}").strip()
            logger.warning("Sandbox pytest installation failed manager=%s", manager)
            return str(python_path), manager, f"Could not install pytest in the {manager} environment:\n{detail[-3000:]}"

    logger.info("Sandbox dependencies installed manager=%s duration_seconds=%.2f", manager, duration)
    return str(python_path), manager, None


def _sandbox_dependency_context(sandbox_dir: Path) -> str:
    manifest_paths = [
        path for path in sandbox_dir.glob("**/pyproject.toml")
        if len(path.relative_to(sandbox_dir).parts) <= 3
    ]
    manifest_paths.extend(
        path for path in sandbox_dir.glob("**/requirements*.txt")
        if len(path.relative_to(sandbox_dir).parts) <= 3
    )
    blocks = []
    remaining_chars = 6000
    for path in manifest_paths[:12]:
        if remaining_chars <= 0:
            break
        content = path.read_text(encoding="utf-8", errors="replace")[:1500]
        block = f"=== {path.relative_to(sandbox_dir)} ===\n{content}"
        blocks.append(block[:remaining_chars])
        remaining_chars -= len(block)
    return "\n\n".join(blocks) or "(No dependency manifest found)"


async def _plan_sandbox_dependencies(
    sandbox_dir: Path,
    setup_error: str,
) -> DependencyInstallPlan:
    prompt = textwrap.dedent(f"""
        Determine the missing Python packages needed to make this repository's pytest suite import and collect.

        Dependency manifests:
        {_sandbox_dependency_context(sandbox_dir)}

        Setup or collection error:
        {setup_error[-6000:]}

        Return ONLY JSON in this exact shape:
        {{"packages": ["package-name"], "reasoning": "brief explanation"}}

        Include only packages that are absent or required by the manifests and traceback.
        Do not return shell commands, URLs, paths, flags, or code.
    """).strip()
    client = get_llm_client()
    response = await client.generate(
        model=model_for("coding"),
        prompt=prompt,
        think=False,
        options={"temperature": 0.0, "num_predict": 512},
        system="You identify Python dependencies. Return only the requested JSON object.",
    )
    from app.agent_service import _extract_json_block

    raw_plan = _extract_json_block(response.response)
    plan = DependencyInstallPlan.model_validate(raw_plan)
    plan.packages = list(dict.fromkeys(plan.packages))
    invalid = [package for package in plan.packages if not PACKAGE_SPEC_RE.fullmatch(package)]
    if invalid:
        raise ValueError(f"LLM returned invalid package specifications: {invalid}")
    return plan


async def _recover_sandbox_dependencies(
    sandbox_dir: Path,
    python_path: str,
    setup_error: str,
    runtime: str,
) -> dict[str, Any]:
    if runtime == "docker" or not Path(python_path).exists():
        return {"recovered": False, "reason": "No writable process sandbox interpreter available."}
    try:
        plan = await _plan_sandbox_dependencies(sandbox_dir, setup_error)
    except Exception as error:
        logger.exception("LLM dependency planning failed sandbox=%s", sandbox_dir)
        return {"recovered": False, "reason": f"Dependency planning failed: {error}"}
    if not plan.packages:
        return {"recovered": False, "reason": "LLM returned no dependency packages."}
    code, out, err, duration = await asyncio.to_thread(
        _run_cmd,
        [python_path, "-m", "pip", "install", "--disable-pip-version-check", *plan.packages],
        sandbox_dir,
        SANDBOX_DEPENDENCY_TIMEOUT_SECONDS,
        runtime=runtime,
    )
    if code != 0:
        return {
            "recovered": False,
            "packages": plan.packages,
            "reason": (err or out)[-3000:],
            "duration_seconds": duration,
        }
    return {
        "recovered": True,
        "packages": plan.packages,
        "reasoning": plan.reasoning,
        "duration_seconds": duration,
    }


def _run_pytest_suite(
    sandbox_dir: Path,
    target_files: list[str],
    timeout: int = 30,
    runtime: str = SANDBOX_RUNTIME,
    python_path_override: str | None = None,
) -> dict[str, Any]:
    """Run pytest suite in the sandbox directory."""
    if python_path_override:
        python_path, dependency_manager, setup_error = python_path_override, "LLM dependency recovery", None
    else:
        python_path, dependency_manager, setup_error = _prepare_test_environment(sandbox_dir, runtime)
    if setup_error:
        return {
            "passed": False,
            "tests_run": 0,
            "passed_count": 0,
            "failed_count": 0,
            "error_count": 1,
            "duration_seconds": 0,
            "dependency_manager": dependency_manager,
            "output": setup_error,
            "summary": f"Dependency setup failed ({dependency_manager})",
            "setup_error": True,
            "python_path": python_path,
        }

    test_dirs = [d for d in ["tests", "test", "testing"] if (sandbox_dir / d).is_dir()]
    if not test_dirs:
        test_dirs = [
            str(path.relative_to(sandbox_dir))
            for path in sandbox_dir.glob("**/tests")
            if path.is_dir()
            and len(path.relative_to(sandbox_dir).parts) <= 3
        ]

    # If specific test files are in target_files, target them directly
    targeted_tests = [f for f in target_files if "test" in f.lower() and f.endswith(".py") and (sandbox_dir / f).exists()]

    cmd = [
        python_path, "-m", "pytest",
        "-q",
        "-o", "addopts=",
        "--import-mode=importlib",
        "--tb=short",
        "--maxfail=5",
        "--disable-warnings",
    ]

    if targeted_tests:
        cmd.extend(targeted_tests)
    elif test_dirs:
        cmd.extend(test_dirs)
    else:
        # Fallback to current directory discovery
        cmd.append(".")

    code, out, err, duration = _run_cmd(cmd, cwd=sandbox_dir, timeout=timeout, runtime=runtime)
    combined_output = (out + "\n" + err).strip()

    # Parse pytest summary line (e.g. "3 passed, 1 failed in 0.45s" or "1 passed in 0.12s")
    passed_count = 0
    failed_count = 0
    error_count = 0

    p_match = re.search(r"(\d+)\s+passed", combined_output)
    if p_match:
        passed_count = int(p_match.group(1))

    f_match = re.search(r"(\d+)\s+failed", combined_output)
    if f_match:
        failed_count = int(f_match.group(1))

    e_match = re.search(r"(\d+)\s+error", combined_output)
    if e_match:
        error_count = int(e_match.group(1))

    total_run = passed_count + failed_count + error_count
    passed = (code in (0, 5)) and (failed_count == 0) and (error_count == 0)

    no_tests_collected = (
        code == 5
        or "no tests ran" in combined_output.lower()
        or "collected 0 items" in combined_output.lower()
    )
    if no_tests_collected:
        return {
            "passed": True,
            "tests_run": 0,
            "passed_count": 0,
            "failed_count": 0,
            "duration_seconds": duration,
            "dependency_manager": dependency_manager,
            "output": combined_output or "No automated test suite discovered in target paths.",
            "summary": "No test regressions (0 tests collected)",
        }

    if total_run == 0:
        return {
            "passed": False,
            "tests_run": 0,
            "passed_count": 0,
            "failed_count": 0,
            "error_count": 1,
            "duration_seconds": duration,
            "dependency_manager": dependency_manager,
            "output": combined_output[-3000:] or f"pytest exited with status {code} before collecting tests",
            "summary": f"Pytest failed before collecting tests (exit code {code})",
        }

    summary = f"{passed_count} passed, {failed_count} failed, {error_count} errors ({duration}s)"
    return {
        "passed": passed,
        "tests_run": total_run,
        "passed_count": passed_count,
        "failed_count": failed_count,
        "error_count": error_count,
        "duration_seconds": duration,
        "dependency_manager": dependency_manager,
        "output": combined_output[-3000:],  # keep last 3000 chars of pytest log
        "summary": summary,
    }


def _run_terminal_check(
    sandbox_dir: Path,
    command: list[str] | None,
    timeout: int,
    runtime: str,
) -> dict[str, Any]:
    """Run a caller-selected, shell-free project check and capture its terminal diagnostics."""
    if not command:
        return {
            "enabled": False,
            "passed": True,
            "command": [],
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "summary": "No terminal check requested",
        }

    executable = Path(command[0]).name
    if executable not in TERMINAL_COMMANDS:
        raise ValueError(f"Unsupported terminal command: {executable}")
    if len(command) > 32 or any(len(token) > 512 for token in command):
        raise ValueError("Terminal command is too long")

    normalized_command = list(command)
    if executable in {"python", "python3"}:
        normalized_command[0] = VENV_PYTHON
    code, stdout, stderr, duration = _run_cmd(
        normalized_command,
        cwd=sandbox_dir,
        timeout=timeout,
        runtime=runtime,
    )
    return {
        "enabled": True,
        "passed": code == 0,
        "command": command,
        "exit_code": code,
        "stdout": stdout[-3000:],
        "stderr": stderr[-3000:],
        "duration_seconds": duration,
        "summary": "Terminal check passed" if code == 0 else f"Terminal check failed (exit code {code})",
    }


async def run_sandbox_validation(
    repo_full_name: str,
    file_rewrites: dict[str, str],
    timeout_seconds: int = 45,
    runtime: str | None = None,
    terminal_command: list[str] | None = None,
) -> dict[str, Any]:
    """
    Copy repo into an isolated temp directory, apply file rewrites,
    and execute syntax checks, linters, type checks, and pytest suite.
    """
    runtime = (runtime or SANDBOX_RUNTIME).lower()
    if runtime not in {"process", "docker"}:
        raise ValueError(f"Unsupported sandbox runtime: {runtime}")

    # 1. Fetch repo
    local_repo = await asyncio.to_thread(_clone_or_get_repo, repo_full_name)

    # 2. Create isolated sandbox directory
    sandbox_id = str(uuid.uuid4())[:8]
    temp_dir = Path(tempfile.gettempdir()) / f"patchwork_sandbox_{sandbox_id}"

    t_start = time.time()
    try:
        # Copy repo files into temp directory (ignoring .git cache to be ultra-fast)
        def _ignore_patterns(path, names):
            return {".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache"}

        await asyncio.to_thread(
            shutil.copytree,
            local_repo,
            temp_dir,
            ignore=_ignore_patterns,
            dirs_exist_ok=True,
        )

        # 3. Apply file rewrites
        for rel_path, content in file_rewrites.items():
            dest_file = _safe_sandbox_path(temp_dir, rel_path)
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            original = dest_file.read_text(encoding="utf-8", errors="replace") if dest_file.exists() else None
            dest_file.write_text(
                _safe_rewrite_content(rel_path, content, original),
                encoding="utf-8",
            )

        target_files = list(file_rewrites.keys())

        logger.info(
            "Sandbox validation started repo=%s sandbox=%s runtime=%s changed_files=%d",
            repo_full_name,
            sandbox_id,
            runtime,
            len(file_rewrites),
        )
        # 4. Run Check Suite in threadpool
        syntax_res = await asyncio.to_thread(_check_syntax, temp_dir, target_files, runtime)
        lint_res = await asyncio.to_thread(_check_linters, temp_dir, target_files, runtime)
        type_res = await asyncio.to_thread(_check_types, temp_dir, target_files, runtime)
        terminal_res = await asyncio.to_thread(
            _run_terminal_check, temp_dir, terminal_command, timeout_seconds, runtime
        )
        test_res = await asyncio.to_thread(
            _run_pytest_suite, temp_dir, target_files, timeout_seconds, runtime
        )
        if test_res.get("setup_error") and runtime == "process":
            recovery = await _recover_sandbox_dependencies(
                sandbox_dir=temp_dir,
                python_path=test_res.get("python_path", ""),
                setup_error=test_res.get("output", ""),
                runtime=runtime,
            )
            test_res["dependency_recovery"] = recovery
            if recovery.get("recovered"):
                test_res = await asyncio.to_thread(
                    _run_pytest_suite,
                    temp_dir,
                    target_files,
                    timeout_seconds,
                    runtime,
                    test_res.get("python_path"),
                )

        total_duration = round(time.time() - t_start, 2)

        # 5. Compute overall score & status
        all_passed = (
            syntax_res["passed"]
            and lint_res["passed"]
            and type_res["passed"]
            and terminal_res["passed"]
            and test_res["passed"]
        )
        has_warnings = (not lint_res["passed"]) or (not type_res["passed"])

        if all_passed and not has_warnings:
            overall_status = "passed"
            score = 100
        elif all_passed and has_warnings:
            overall_status = "warnings"
            score = 85
        else:
            overall_status = "failed"
            score = max(0, 50 - (test_res.get("failed_count", 1) * 15))

        return {
            "success": all_passed,
            "overall_status": overall_status,
            "score": score,
            "execution_time_seconds": total_duration,
            "environment": f"{runtime}_sandbox",
            "checks": {
                "syntax": syntax_res,
                "linter": lint_res,
                "type_check": type_res,
                "terminal": terminal_res,
                "tests": test_res,
            },
            "summary": f"{test_res['summary']} | {lint_res['summary']} | {type_res['summary']}",
            "modified_files": target_files,
        }

    finally:
        # 6. Teardown & cleanup sandbox directory
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)

            logger.info(
                "Sandbox validation completed repo=%s sandbox=%s status=%s duration_seconds=%.2f",
                repo_full_name,
                sandbox_id,
                locals().get("overall_status", "error"),
                round(time.time() - t_start, 2),
            )

async def auto_heal_code(
    repo_full_name: str,
    feature_or_issue_title: str,
    file_rewrites: dict[str, str],
    sandbox_diagnostics: dict[str, Any],
    attempt: int = 1,
    max_attempts: int | None = MAX_HEAL_ATTEMPTS,
    diff_history: list[dict[str, Any]] | None = None,
    runtime: str | None = None,
    terminal_command: list[str] | None = None,
) -> dict[str, Any]:
    """
    Prompt the configured AI provider with validation diagnostics to automatically
    heal and regenerate clean, working file rewrites.

    Continues until the sandbox passes. Each attempt is tracked in diff_history
    so the LLM and caller can see what was already tried. Set
    OPENROUTER_HEAL_MAX_ATTEMPTS to an integer when an operational cap is needed.
    """
    if diff_history is None:
        diff_history = []

    if max_attempts is None:
        configured_limit = os.getenv("OPENROUTER_HEAL_MAX_ATTEMPTS", "").strip()
        max_attempts = int(configured_limit) if configured_limit else None

    if max_attempts is not None and attempt > max_attempts:
        return {
            "file_rewrites": file_rewrites,
            "healing_analysis": (
                f"Exhausted {max_attempts} heal attempts without passing all checks. "
                "Manual review is required."
            ),
            "healed": False,
            "attempts_used": attempt - 1,
            "diff_history": diff_history,
            "sandbox_result": sandbox_diagnostics,
        }

    client = get_llm_client()

    test_output = sandbox_diagnostics.get("checks", {}).get("tests", {}).get("output", "")
    syntax_errors = sandbox_diagnostics.get("checks", {}).get("syntax", {}).get("errors", [])
    lint_warnings = sandbox_diagnostics.get("checks", {}).get("linter", {}).get("warnings", [])
    type_errors = sandbox_diagnostics.get("checks", {}).get("type_check", {}).get("errors", [])
    terminal_check = sandbox_diagnostics.get("checks", {}).get("terminal", {})

    current_code_blocks = "\n\n".join(
        f"=== FILE: {path} ===\n{content}\n=== END FILE ==="
        for path, content in file_rewrites.items()
    )

    prior_attempts_block = ""
    if diff_history:
        prior_attempts_block = "\n\nPRIOR HEAL ATTEMPTS (do NOT repeat the same fix):\n"
        for entry in diff_history:
            prior_attempts_block += (
                f"- Attempt {entry['attempt']}: {entry['analysis']}\n"
                f"  Result: {entry['result_summary']}\n"
            )

    heal_prompt = textwrap.dedent(f"""
        You are an expert Python engineer fixing code that failed sandbox validation tests or linters.

        Repository: {repo_full_name}
        Context: {feature_or_issue_title}
        Heal attempt: {attempt} ({'unlimited' if max_attempts is None else f'of {max_attempts}'})

        CURRENT PROPOSED CODE:
        {current_code_blocks}

        VALIDATION DIAGNOSTICS & TRACEBACKS:
        - Syntax Errors: {json.dumps(syntax_errors, indent=2)}
        - Test Suite Failure Log:
        {test_output or '(No pytest output)'}
        - Type Errors: {json.dumps(type_errors, indent=2)}
        - Lint Warnings: {json.dumps(lint_warnings[:5], indent=2)}
        - Terminal Check: {json.dumps(terminal_check, indent=2)}
        {prior_attempts_block}

        Instructions:
        Ponytail "Lazy Senior Dev" Guidelines:
        - Prefer the simplest, shortest working diff to fix the tests (delete over addition).
        - Fix root causes (shared functions), not just symptoms.
        - No unrequested boilerplate or premature abstractions.
        - Never compromise on security or error handling.

        1. Analyze the exact failure traceback and errors.
        2. Fix the bug, broken imports, missing methods, or syntax errors.
        3. Output the COMPLETE corrected file contents for each file that needs changes.
        4. Use EXACT format:
        === FILE: path/to/file.py ===
        <complete corrected file content>
        === END FILE ===

        After the file blocks, provide a short ANALYSIS:
        ANALYSIS:
        - Root cause of the failure (1-2 sentences)
        - How the fix resolves the tests (1-2 sentences)
    """).strip()

    resp = await client.generate(
        model=model_for("coding"),
        prompt=heal_prompt,
        think=False,
        system="You are an expert code debugger. Output corrected files in === FILE: ... === format, followed by ANALYSIS.",
        options={"temperature": 0.1, "num_predict": 4096},
    )

    raw = resp.response
    from app.agent_service import _parse_file_rewrites

    parsed_rewrites = _parse_file_rewrites(raw)
    parsed_rewrites = {
        path: content
        for path, content in parsed_rewrites.items()
        if "=== FILE:" not in content and "=== END FILE ===" not in content
    }
    new_rewrites = {**file_rewrites, **parsed_rewrites}

    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=re.IGNORECASE).strip()
    analysis_match = re.search(r"ANALYSIS:([\s\S]+)", cleaned or raw, re.IGNORECASE)
    analysis_text = analysis_match.group(1).strip() if analysis_match else "Automatically resolved test failures."

    revalidation = await run_sandbox_validation(
        repo_full_name=repo_full_name,
        file_rewrites=new_rewrites,
        terminal_command=terminal_command,
        runtime=runtime,
    )

    diff_history.append({
        "attempt": attempt,
        "analysis": analysis_text[:200],
        "result_summary": revalidation.get("summary", "unknown"),
        "passed": revalidation.get("success", False),
    })

    if revalidation.get("overall_status") == "passed":
        return {
            "file_rewrites": new_rewrites,
            "healing_analysis": analysis_text,
            "healed": True,
            "attempts_used": attempt,
            "diff_history": diff_history,
            "sandbox_result": revalidation,
        }

    return await auto_heal_code(
        repo_full_name=repo_full_name,
        feature_or_issue_title=feature_or_issue_title,
        file_rewrites=new_rewrites,
        sandbox_diagnostics=revalidation,
        attempt=attempt + 1,
        max_attempts=max_attempts,
        diff_history=diff_history,
        runtime=runtime,
        terminal_command=terminal_command,
    )


async def run_sandbox_validation_with_auto_heal(
    repo_full_name: str,
    title: str,
    file_rewrites: dict[str, str],
    runtime: str | None = None,
    terminal_command: list[str] | None = None,
) -> dict[str, Any]:
    """Verify proposed code and automatically repair failures in isolated copies."""
    initial_result = await run_sandbox_validation(
        repo_full_name=repo_full_name,
        file_rewrites=file_rewrites,
        terminal_command=terminal_command,
        runtime=runtime,
    )
    if initial_result.get("overall_status") == "passed":
        return initial_result

    try:
        healing = await auto_heal_code(
            repo_full_name=repo_full_name,
            feature_or_issue_title=title,
            file_rewrites=file_rewrites,
            sandbox_diagnostics=initial_result,
            terminal_command=terminal_command,
            runtime=runtime,
        )
    except Exception:
        logger.exception("Automatic sandbox repair failed repo=%s", repo_full_name)
        return {
            **initial_result,
            "file_rewrites": file_rewrites,
            "healing_analysis": "Automatic repair failed; original sandbox diagnostics are shown.",
            "healed": False,
            "healing_attempts": 0,
            "healing_history": [],
        }
    final_result = healing.get("sandbox_result") or initial_result
    return {
        **final_result,
        "file_rewrites": healing.get("file_rewrites", file_rewrites),
        "healing_analysis": healing.get("healing_analysis"),
        "healed": healing.get("healed", False),
        "healing_attempts": healing.get("attempts_used", 0),
        "healing_history": healing.get("diff_history", []),
    }
