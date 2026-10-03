"""Concrete, bounded tools exposed to the contribution agent."""

from __future__ import annotations

import asyncio
import re
import subprocess
from pathlib import Path
from typing import Any

from app.agent_runtime import ToolRegistry, ToolSpec
from app.github_service import GitHubService


MAX_TOOL_OUTPUT = 100_000


def _safe_path(root: Path, relative_path: str) -> Path:
    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise ValueError("Tool paths must be relative")
    resolved_root = root.resolve()
    resolved = (resolved_root / candidate).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError("Tool path escapes repository root") from error
    return resolved


def _list_files(arguments: dict[str, Any]) -> dict[str, Any]:
    root = Path(arguments["repository_root"])
    pattern = str(arguments.get("pattern", "*.py"))
    limit = min(max(int(arguments.get("limit", 200)), 1), 500)
    files = [
        str(path.relative_to(root))
        for path in sorted(root.glob(pattern))
        if path.is_file() and ".git" not in path.parts and "node_modules" not in path.parts
    ][:limit]
    return {"files": files, "truncated": len(files) == limit}


def _read_file(arguments: dict[str, Any]) -> dict[str, Any]:
    root = Path(arguments["repository_root"])
    path = _safe_path(root, str(arguments["path"]))
    if not path.is_file():
        raise ValueError("Repository file does not exist")
    max_chars = min(max(int(arguments.get("max_chars", 20_000)), 1), 50_000)
    content = path.read_text(errors="replace")
    return {"path": str(path.relative_to(root)), "content": content[:max_chars], "truncated": len(content) > max_chars}


def _search_files(arguments: dict[str, Any]) -> dict[str, Any]:
    root = Path(arguments["repository_root"])
    pattern = re.compile(str(arguments["query"]), re.IGNORECASE)
    limit = min(max(int(arguments.get("limit", 100)), 1), 500)
    matches: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".git" in path.parts or "node_modules" in path.parts:
            continue
        try:
            lines = path.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for line_number, line in enumerate(lines, 1):
            if pattern.search(line):
                matches.append({"path": str(path.relative_to(root)), "line": line_number, "text": line[:500]})
                if len(matches) >= limit:
                    return {"matches": matches, "truncated": True}
    return {"matches": matches, "truncated": False}


def _git_log(arguments: dict[str, Any]) -> dict[str, Any]:
    root = Path(arguments["repository_root"])
    count = min(max(int(arguments.get("count", 20)), 1), 100)
    completed = subprocess.run(
        ["git", "log", f"-{count}", "--format=%H%x09%ad%x09%s", "--date=iso"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    return {"commits": completed.stdout[-MAX_TOOL_OUTPUT:]}


def _run_tests(arguments: dict[str, Any]) -> dict[str, Any]:
    root = Path(arguments["repository_root"])
    command = arguments.get("command", ["python", "-m", "pytest", "-q"])
    if not isinstance(command, list) or not command or command[0] not in {"python", "python3", "pytest"}:
        raise ValueError("Only python or pytest test commands are allowed")
    completed = subprocess.run(
        [str(part) for part in command],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=min(max(int(arguments.get("timeout", 45)), 1), 120),
        check=False,
    )
    return {
        "command": command,
        "exit_code": completed.returncode,
        "stdout": completed.stdout[-MAX_TOOL_OUTPUT:],
        "stderr": completed.stderr[-MAX_TOOL_OUTPUT:],
    }


async def _github_issue_context(arguments: dict[str, Any]) -> dict[str, Any]:
    repository = str(arguments["repository"])
    issue_number = int(arguments["issue_number"])
    service = GitHubService()

    def fetch() -> dict[str, Any]:
        issue = service.client.get_repo(repository).get_issue(issue_number)
        return {
            "repository": repository,
            "number": issue.number,
            "title": issue.title,
            "body": issue.body or "",
            "labels": [label.name for label in issue.labels],
            "assignees": [user.login for user in issue.assignees],
            "comments": issue.comments,
        }

    return await asyncio.to_thread(fetch)


def build_repository_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ToolSpec("list_repository_files", _list_files, False))
    registry.register(ToolSpec("read_repository_file", _read_file, False))
    registry.register(ToolSpec("search_repository", _search_files, False))
    registry.register(ToolSpec("inspect_git_history", _git_log, False))
    registry.register(ToolSpec("run_repository_tests", _run_tests, True))
    registry.register(ToolSpec("read_github_issue", _github_issue_context, False))
    return registry
