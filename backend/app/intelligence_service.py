"""Repository structure extraction for agent context and contribution scoring."""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from typing import Any

from app.agent_service import _clone_or_update


def _module_name(root: Path, path: Path) -> str:
    return ".".join(path.relative_to(root).with_suffix("").parts)


def _build_graph(local: Path, max_files: int = 250) -> dict[str, Any]:
    modules: list[dict[str, Any]] = []
    symbols: list[dict[str, str]] = []
    imports: list[dict[str, str]] = []
    tests: list[str] = []

    python_files = sorted(
        path for path in local.rglob("*.py")
        if ".git" not in path.parts
        and ".venv" not in path.parts
        and "venv" not in path.parts
        and "node_modules" not in path.parts
    )[:max_files]

    for path in python_files:
        relative = str(path.relative_to(local))
        module = _module_name(local, path)
        try:
            tree = ast.parse(path.read_text(errors="replace"), filename=relative)
        except (OSError, SyntaxError):
            continue

        module_symbols = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                kind = "class" if isinstance(node, ast.ClassDef) else "function"
                module_symbols.append(node.name)
                symbols.append({"module": module, "name": node.name, "kind": kind})
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append({"module": module, "imports": alias.name})
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append({"module": module, "imports": node.module})

        is_test = path.name.startswith("test_") or path.parent.name in {"test", "tests", "testing"}
        if is_test:
            tests.append(relative)
        modules.append({
            "path": relative,
            "module": module,
            "symbols": module_symbols,
            "is_test": is_test,
        })

    module_names = {item["module"] for item in modules}
    dependency_edges = [
        item for item in imports
        if item["imports"] in module_names or any(
            name.startswith(f"{item['imports']}.") for name in module_names
        )
    ]
    return {
        "files_scanned": len(modules),
        "symbol_count": len(symbols),
        "test_file_count": len(tests),
        "modules": modules,
        "symbols": symbols,
        "imports": imports,
        "dependency_edges": dependency_edges,
        "test_files": tests,
    }


async def build_repository_graph(repo_full_name: str) -> dict[str, Any]:
    local = await asyncio.to_thread(_clone_or_update, repo_full_name)
    return await asyncio.to_thread(_build_graph, local)