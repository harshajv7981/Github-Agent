"""Shared repository, parsing, and response-normalization helpers for agents."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

REPOS_CACHE_DIR = Path.home() / ".patchwork" / "repos"
logger = logging.getLogger(__name__)
MAX_FILE_CHARS = 6000
MAX_FILES = 4

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _run(
    cmd: list[str],
    cwd: Optional[Path] = None,
    check: bool = True,
    timeout: int = 120,
) -> str:
    result = subprocess.run(
        cmd, cwd=str(cwd) if cwd else None,
        capture_output=True, text=True, timeout=timeout
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"Command {' '.join(cmd)} failed:\n{result.stderr}")
    return result.stdout.strip()


def _clone_or_update(repo_full_name: str) -> Path:
    """Clone the repo to the local cache dir; pull if already cloned."""
    owner, name = repo_full_name.split("/")
    local = REPOS_CACHE_DIR / owner / name
    local.parent.mkdir(parents=True, exist_ok=True)

    clone_url = f"https://github.com/{repo_full_name}.git"
    if not (local / ".git").exists():
        _run(["git", "clone", "--depth", "50", clone_url, str(local)], check=True)
    else:
        try:
            _run(["git", "fetch", "--depth", "50", "origin"], cwd=local)
            _run(["git", "reset", "--hard", "origin/HEAD"], cwd=local)
        except Exception:
            pass  # stale cache is still usable

    return local


def _cleanup_repo_cache(repo_full_name: str, cache_dir: Path | None = None) -> None:
    """Remove the supported cached clones after a pull request is opened."""
    parts = repo_full_name.split("/")
    if len(parts) != 2 or any(part in {"", ".", ".."} for part in parts):
        logger.warning("Skipping clone cleanup for invalid repository name")
        return

    owner, name = parts
    cache_dir = cache_dir or REPOS_CACHE_DIR
    cache_paths = (
        cache_dir / owner / name,
        cache_dir / f"{owner}__{name}",
    )
    for cache_path in cache_paths:
        try:
            shutil.rmtree(cache_path)
        except FileNotFoundError:
            pass
        except OSError:
            logger.warning("Could not remove cached repository clone path=%s", cache_path, exc_info=True)


def _repo_file_tree(local: Path, max_files: int = 200) -> str:
    """Return a compact tree of Python files for Ollama to reason about."""
    files = sorted(local.rglob("*.py"))
    files = [f for f in files if ".git" not in f.parts and "venv" not in f.parts
             and "node_modules" not in f.parts][:max_files]
    return "\n".join(str(f.relative_to(local)) for f in files)


def _read_file(local: Path, rel_path: str) -> str:
    full = _safe_repo_path(local, rel_path)
    if full is None:
        return ""
    if not full.exists():
        return ""
    text = full.read_text(errors="replace")
    if len(text) > MAX_FILE_CHARS:
        text = text[:MAX_FILE_CHARS] + f"\n\n[...truncated at {MAX_FILE_CHARS} chars]"
    return text


def _safe_repo_path(root: Path, rel_path: str) -> Path | None:
    candidate = Path(rel_path.strip())
    if candidate.is_absolute():
        return None

    root_resolved = root.resolve()
    path_resolved = (root_resolved / candidate).resolve()
    try:
        path_resolved.relative_to(root_resolved)
    except ValueError:
        return None
    return path_resolved


def _extract_json_block(text: str) -> dict | list:
    """Pull the first JSON object or list out of a free-form Ollama response."""
    import json

    # Strip thinking / reasoning tags if present
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()
    if not cleaned:
        cleaned = text.strip()

    # 1. Direct parse
    try:
        return json.loads(cleaned)
    except Exception:
        pass

    # 2. Markdown code blocks ```json ... ``` or ``` ... ```
    for m in re.finditer(r"```(?:json)?\s*([\s\S]+?)\s*```", cleaned):
        try:
            return json.loads(m.group(1).strip())
        except Exception:
            pass

    # 3. Precise balanced-brace search for outermost { ... } or [ ... ]
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start_idx = cleaned.find(start_char)
        if start_idx != -1:
            depth = 0
            in_string = False
            escape = False
            for i in range(start_idx, len(cleaned)):
                c = cleaned[i]
                if escape:
                    escape = False
                    continue
                if c == "\\":
                    escape = True
                    continue
                if c == '"':
                    in_string = not in_string
                    continue
                if not in_string:
                    if c == start_char:
                        depth += 1
                    elif c == end_char:
                        depth -= 1
                        if depth == 0:
                            candidate = cleaned[start_idx : i + 1]
                            try:
                                return json.loads(candidate)
                            except Exception:
                                pass
                            break

    # 4. Fallback search
    match = re.search(r"\{[\s\S]+\}", cleaned)
    if match:
        raw_obj = match.group()
        for end_idx in range(len(raw_obj), 0, -1):
            if raw_obj[end_idx - 1] == "}":
                try:
                    return json.loads(raw_obj[:end_idx])
                except Exception:
                    continue

    return {}


def _clean_analysis_text(raw: str, analysis_match: re.Match[str] | None) -> str:
    candidate = analysis_match.group(1).strip() if analysis_match else ""
    candidate = re.sub(r"<think>[\s\S]*?</think>", "", candidate, flags=re.IGNORECASE).strip()
    if re.search(r"(?:_popip[46])(?:[46z]){12,}", raw, re.IGNORECASE):
        return "The model returned malformed reasoning output; review the proposed files and validation results."
    if not candidate or "=== FILE:" in candidate or "=== END FILE ===" in candidate:
        return "The model returned an invalid analysis response; review the proposed files and validation results."
    if len(candidate) > 2000 or len(candidate.split()) > 350:
        return "The model returned an oversized analysis response; review the proposed files and validation results."
    return candidate


def _parse_file_rewrites(text: str) -> dict[str, str]:
    """
    Parse Ollama response for file rewrites.
    Expects sections like:
      === FILE: path/to/file.py ===
      <new content>
      === END FILE ===
    """
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()
    target_text = cleaned if cleaned else text
    rewrites: dict[str, str] = {}
    blocks = re.findall(
        r"=== FILE:\s*(.+?)\s*===\n([\s\S]+?)=== END FILE ===",
        target_text, re.IGNORECASE
    )
    for path, content in blocks:
        rewrites[path.strip()] = content.strip("\n")
    return rewrites


