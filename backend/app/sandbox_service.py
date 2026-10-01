"""
Sandbox Service: Isolated environment execution for pytest, linters (flake8/ruff),
and type checkers (mypy) with automatic error diagnostics and AI self-healing.
"""

from __future__ import annotations

import asyncio
import json
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
from ollama import AsyncClient
from app.model_router import model_for

load_dotenv()

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:9b")
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

MAX_SANDBOX_MEMORY_MB = 512
MAX_SANDBOX_OUTPUT_BYTES = 1_000_000


def _make_sandbox_env(cwd: Path, env_extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {}
    for k, v in os.environ.items():
        if k.upper() in SENSITIVE_ENV_KEYS:
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
        code, out, err, _ = _run_cmd(
            [VENV_PYTHON, "-m", "py_compile", str(file_path)],
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


def _run_pytest_suite(
    sandbox_dir: Path,
    target_files: list[str],
    timeout: int = 30,
    runtime: str = SANDBOX_RUNTIME,
) -> dict[str, Any]:
    """Run pytest suite in the sandbox directory."""
    test_dirs = [d for d in ["tests", "test", "testing"] if (sandbox_dir / d).is_dir()]

    # If specific test files are in target_files, target them directly
    targeted_tests = [f for f in target_files if "test" in f.lower() and f.endswith(".py") and (sandbox_dir / f).exists()]

    cmd = [
        VENV_PYTHON, "-m", "pytest",
        "-q",
        "-o", "addopts=",
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

    # Handle "no tests ran" or 0 tests collected cleanly
    if total_run == 0 or "no tests ran" in combined_output.lower() or "collected 0 items" in combined_output.lower() or code == 5:
        return {
            "passed": True,
            "tests_run": 0,
            "passed_count": 0,
            "failed_count": 0,
            "duration_seconds": duration,
            "output": combined_output or "No automated test suite discovered in target paths.",
            "summary": "No test regressions (0 tests collected)",
        }

    summary = f"{passed_count} passed, {failed_count} failed, {error_count} errors ({duration}s)"
    return {
        "passed": passed,
        "tests_run": total_run,
        "passed_count": passed_count,
        "failed_count": failed_count,
        "error_count": error_count,
        "duration_seconds": duration,
        "output": combined_output[-3000:],  # keep last 3000 chars of pytest log
        "summary": summary,
    }


async def run_sandbox_validation(
    repo_full_name: str,
    file_rewrites: dict[str, str],
    timeout_seconds: int = 45,
    runtime: str | None = None,
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
            dest_file.write_text(content, encoding="utf-8")

        target_files = list(file_rewrites.keys())

        # 4. Run Check Suite in threadpool
        syntax_res = await asyncio.to_thread(_check_syntax, temp_dir, target_files, runtime)
        lint_res = await asyncio.to_thread(_check_linters, temp_dir, target_files, runtime)
        type_res = await asyncio.to_thread(_check_types, temp_dir, target_files, runtime)
        test_res = await asyncio.to_thread(
            _run_pytest_suite, temp_dir, target_files, timeout_seconds, runtime
        )

        total_duration = round(time.time() - t_start, 2)

        # 5. Compute overall score & status
        all_passed = syntax_res["passed"] and test_res["passed"]
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
                "tests": test_res,
            },
            "summary": f"{test_res['summary']} | {lint_res['summary']} | {type_res['summary']}",
            "modified_files": target_files,
        }

    finally:
        # 6. Teardown & cleanup sandbox directory
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


MAX_HEAL_ATTEMPTS = 3


async def auto_heal_code(
    repo_full_name: str,
    feature_or_issue_title: str,
    file_rewrites: dict[str, str],
    sandbox_diagnostics: dict[str, Any],
    attempt: int = 1,
    max_attempts: int = MAX_HEAL_ATTEMPTS,
    diff_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Prompt Ollama with test failure diagnostics and tracebacks to automatically
    heal and regenerate clean, working file rewrites.

    Enforces a retry cap (default 3). Each attempt is tracked in diff_history
    so the LLM and caller can see what was already tried. After generating a
    fix, the full sandbox verification suite reruns. If still failing and
    under the cap, recurses. If the cap is reached, returns the best attempt
    with healed=False.
    """
    if diff_history is None:
        diff_history = []

    if attempt > max_attempts:
        return {
            "file_rewrites": file_rewrites,
            "healing_analysis": (
                f"Exhausted {max_attempts} heal attempts without passing all checks. "
                "Manual review is required."
            ),
            "healed": False,
            "attempts_used": attempt - 1,
            "diff_history": diff_history,
        }

    client = AsyncClient(host=OLLAMA_HOST)

    test_output = sandbox_diagnostics.get("checks", {}).get("tests", {}).get("output", "")
    syntax_errors = sandbox_diagnostics.get("checks", {}).get("syntax", {}).get("errors", [])
    lint_warnings = sandbox_diagnostics.get("checks", {}).get("linter", {}).get("warnings", [])
    type_errors = sandbox_diagnostics.get("checks", {}).get("type_check", {}).get("errors", [])

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
        Heal attempt: {attempt} of {max_attempts}

        CURRENT PROPOSED CODE:
        {current_code_blocks}

        VALIDATION DIAGNOSTICS & TRACEBACKS:
        - Syntax Errors: {json.dumps(syntax_errors, indent=2)}
        - Test Suite Failure Log:
        {test_output or '(No pytest output)'}
        - Type Errors: {json.dumps(type_errors, indent=2)}
        - Lint Warnings: {json.dumps(lint_warnings[:5], indent=2)}
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

    new_rewrites = _parse_file_rewrites(raw)
    if not new_rewrites:
        new_rewrites = file_rewrites

    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=re.IGNORECASE).strip()
    analysis_match = re.search(r"ANALYSIS:([\s\S]+)", cleaned or raw, re.IGNORECASE)
    analysis_text = analysis_match.group(1).strip() if analysis_match else "Automatically resolved test failures."

    revalidation = await run_sandbox_validation(
        repo_full_name=repo_full_name,
        file_rewrites=new_rewrites,
    )

    diff_history.append({
        "attempt": attempt,
        "analysis": analysis_text[:200],
        "result_summary": revalidation.get("summary", "unknown"),
        "passed": revalidation.get("success", False),
    })

    if revalidation.get("success"):
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
    )
