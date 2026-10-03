"""Feature ideation, implementation, and feature PR workflows."""

from __future__ import annotations

import asyncio
import json
import re
import textwrap
from typing import Any

from github import Github

from app.agent_service import (
    GITHUB_TOKEN,
    _clone_or_update,
    _extract_json_block,
    _get_or_create_fork,
    _open_github_pr,
    _parse_file_rewrites,
    _read_file,
    _repo_file_tree,
    _run,
    _safe_repo_path,
    logger,
)
from app.llm_client import get_llm_client
from app.model_router import model_for

async def suggest_features_for_repo(
    repo_full_name: str,
    repo_description: str = "",
) -> list[dict]:
    """
    Clone repo, read README/config and file tree, ask Ollama to suggest 3-5 concrete feature proposals.
    """
    client = get_llm_client()
    local = await asyncio.to_thread(_clone_or_update, repo_full_name)
    file_tree = await asyncio.to_thread(_repo_file_tree, local)

    # Read README if present
    readme_text = ""
    for rname in ["README.md", "README.rst", "README.txt", "readme.md"]:
        rpath = local / rname
        if rpath.exists():
            readme_text = rpath.read_text(errors="replace")[:3000]
            break

    # Read config if present
    config_text = ""
    for cname in ["pyproject.toml", "setup.py", "requirements.txt"]:
        cpath = local / cname
        if cpath.exists():
            config_text += f"\n--- {cname} ---\n" + cpath.read_text(errors="replace")[:1500]

    prompt = textwrap.dedent(f"""
        You are a principal software engineer and open-source maintainer analyzing a repository for high-value feature improvements.

        Repository: {repo_full_name}
        Description: {repo_description or '(No description provided)'}

        Project README:
        {readme_text or '(No README found)'}

        Configuration files:
        {config_text or '(No configuration files found)'}

        Python source tree:
        {file_tree}

        Instructions:
        Suggest exactly 3 to 5 realistic, high-impact feature additions, optimizations, or architectural enhancements suitable for an open-source pull request.
        Ponytail "Lazy Senior Dev" Guidelines:
        - Suggest pragmatic, focused enhancements rather than grandiose rewrites.
        - The best code is the code never written. Suggest deletions of dead code, consolidations of duplicate logic, or using standard libraries to remove dependencies.
        - Focus on root causes of technical debt.
        
        Cover different areas:
        - New feature or capability (e.g., CLI commands, format exporters, async support)
        - Performance / Memory optimization
        - Type safety, modern Python typing, or schema validation
        - Developer tooling, testing coverage, or logging/observability

        Respond with ONLY a JSON object containing a "suggestions" list formatted like:
        {{
            "suggestions": [
                {{
                    "title": "Add JSON Lines streaming output for export commands",
                    "category": "feature",
                    "complexity": "intermediate",
                    "impact_score": 85,
                    "description": "Currently exports only support in-memory CSV/JSON which exhausts memory on large datasets. Adding JSONL streaming enables handling arbitrarily large outputs with constant memory usage.",
                    "implementation_plan": "1. Add jsonlines dependency or use builtin json streaming\\n2. Extend export CLI with --format=jsonl\\n3. Add generator-based stream writer in utils/export.py\\n4. Add unit test for chunked writing",
                    "suggested_files": ["src/export.py", "src/cli.py"]
                }}
            ]
        }}

        Valid categories: "feature", "optimization", "type_safety", "tooling", "testing", "documentation"
        Valid complexity: "easy", "intermediate", "advanced"
        impact_score: Integer between 50 and 95
    """).strip()

    resp = await client.generate(
        model=model_for("triage"),
        prompt=prompt,
        think=False,
        system="You are an open-source technical architect. Respond ONLY with a valid JSON object containing the 'suggestions' list. Do not include thinking or preamble.",
        options={"temperature": 0.2, "num_predict": 3072},
    )

    data = _extract_json_block(resp.response)
    if isinstance(data, dict):
        suggestions = data.get("suggestions", [])
        if not isinstance(suggestions, list):
            suggestions = []
    elif isinstance(data, list):
        suggestions = data
    else:
        suggestions = []

    clean_suggestions = []
    for s in suggestions:
        if isinstance(s, dict) and s.get("title") and s.get("description"):
            clean_suggestions.append({
                "title": str(s.get("title", "")).strip(),
                "category": str(s.get("category", "feature")).lower(),
                "complexity": str(s.get("complexity", "intermediate")).lower(),
                "impact_score": max(50, min(100, int(s.get("impact_score", 75)))),
                "description": str(s.get("description", "")).strip(),
                "implementation_plan": str(s.get("implementation_plan", "")).strip(),
                "suggested_files": [str(f) for f in s.get("suggested_files", []) if isinstance(f, str)],
            })

    return clean_suggestions


async def implement_feature(
    repo_full_name: str,
    feature_title: str,
    feature_description: str,
    implementation_plan: str,
    suggested_files: list[str],
) -> dict:
    """
    Clone repo, read relevant files, prompt Ollama to generate complete code rewrites for the feature.
    """
    client = get_llm_client()
    local = await asyncio.to_thread(_clone_or_update, repo_full_name)
    file_tree = await asyncio.to_thread(_repo_file_tree, local)

    if not suggested_files:
        selection_prompt = textwrap.dedent(f"""
            Repository: {repo_full_name}
            Feature to implement: {feature_title}
            Description: {feature_description}
            Plan: {implementation_plan}

            Python files in repository:
            {file_tree}

            List up to {MAX_FILES} file paths that need to be created or modified.
            Respond with ONLY JSON: {{"files": ["path/to/file.py"]}}
        """).strip()

        sel_resp = await client.generate(
            model=model_for("triage"),
            prompt=selection_prompt,
            think=False,
            options=_json_options({"temperature": 0.1, "num_predict": 512}),
        )
        sel_data = _extract_json_block(sel_resp.response)
        suggested_files = sel_data.get("files", [])[:MAX_FILES]

    file_contents: dict[str, str] = {}
    for rel_path in suggested_files:
        content = await asyncio.to_thread(_read_file, local, rel_path)
        if content:
            file_contents[rel_path] = content
        else:
            file_contents[rel_path] = "# (New file to be created)"

    files_block = "\n\n".join(
        f"### {path}\n```python\n{content}\n```"
        for path, content in file_contents.items()
    )

    impl_prompt = textwrap.dedent(f"""
        You are a senior open-source contributor implementing a new feature or improvement.

        Repository: {repo_full_name}
        Feature: {feature_title}
        Description: {feature_description}
        Plan: {implementation_plan}

        Target source files:
        {files_block}

        Instructions:
        - Implement the complete, working code for this feature.
        - Match the existing codebase architecture, idioms, and code style.
        - For every file you create or modify, output the COMPLETE file content (not a partial diff).

        Ponytail "Lazy Senior Dev" Guidelines:
        - YAGNI (You Aren't Gonna Need It): Do not build things unless explicitly required.
        - Reuse existing codebase helpers, utils, and standard library features before writing new code.
        - Delete over addition. Ensure the shortest, simplest working diff.
        - No unrequested boilerplate or premature abstractions.
        - Fix root causes (shared functions), not just symptoms (call locations).
        - Maintain strict security, error handling, and trust boundary validations (do not be lazy about correctness).
        - Format each file EXACTLY like:

        === FILE: path/to/file.py ===
        <complete file content here>
        === END FILE ===

        After all file blocks, write an ANALYSIS section:
        ANALYSIS:
        - Architectural summary of what was added/changed (2-3 sentences)
        - How to test and verify the feature (2-3 bullet points)
        PR TITLE: {feature_title}
    """).strip()

    impl_resp = await client.generate(
        model=model_for("coding"),
        prompt=impl_prompt,
        think=False,
        system="You are an expert open-source maintainer implementing a feature. Output full file rewrites in === FILE: ... === format, followed by ANALYSIS and PR TITLE. Do not include thinking tokens.",
        options={"temperature": 0.2, "num_predict": 4096},
    )
    raw = impl_resp.response

    file_rewrites = _parse_file_rewrites(raw)
    cleaned_raw = re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=re.IGNORECASE).strip()
    analysis_match = re.search(r"ANALYSIS:([\s\S]+?)(?:PR TITLE:|$)", cleaned_raw or raw, re.IGNORECASE)
    analysis_text = _clean_analysis_text(raw, analysis_match)

    pr_title_match = re.search(r"PR TITLE:\s*(.+)", raw, re.IGNORECASE)
    pr_title = pr_title_match.group(1).strip() if pr_title_match else f"Feat: {feature_title}"
    pr_title = pr_title.strip('"\'')

    pr_body = textwrap.dedent(f"""
        ## Feature: {feature_title}

        ### Motivation & Overview
        {feature_description}

        ### Implementation Details
        {analysis_text}

        ### Verification
        - Review modified & added files
        - Run test suite

        ---
        *Generated by [Patchwork](https://github.com) — AI open-source contribution agent*
    """).strip()

    return {
        "analysis": analysis_text,
        "file_rewrites": file_rewrites,
        "pr_title": pr_title,
        "pr_body": pr_body,
        "relevant_files": list(file_rewrites.keys()) or suggested_files,
    }


async def create_feature_pull_request(
    repo_full_name: str,
    feature_id: int,
    pr_title: str,
    pr_body: str,
    file_rewrites: dict[str, str],
) -> dict:
    """
    Apply file rewrites for a feature in a fork and open a PR.
    Runs pre-flight checks for duplicates and contribution policy.

    Returns:
        {"pr_url": str, "pr_number": int, "branch": str, "preflight": dict}
    """
    if not GITHUB_TOKEN:
        raise RuntimeError("GITHUB_TOKEN is not set — cannot create PR")

    branch = f"patchwork/feature-{feature_id}"

    from app.github_service import GitHubService
    gh_svc = GitHubService(GITHUB_TOKEN)
    preflight = gh_svc.run_pr_preflight(repo_full_name, branch)
    if not preflight["ok"]:
        raise RuntimeError(
            f"PR pre-flight blocked: {'; '.join(preflight['blockers'])}"
        )

    gh = Github(GITHUB_TOKEN)
    user = gh.get_user()
    upstream = gh.get_repo(repo_full_name)

    fork = await asyncio.to_thread(_get_or_create_fork, user, upstream)

    local = await asyncio.to_thread(_clone_or_update, repo_full_name)
    fork_remote_url = f"https://x-access-token:{GITHUB_TOKEN}@github.com/{fork.full_name}.git"

    try:
        _run(["git", "remote", "remove", "fork"], cwd=local, check=False)
    except Exception:
        pass
    _run(["git", "remote", "add", "fork", fork_remote_url], cwd=local)

    _run(["git", "fetch", "origin"], cwd=local)
    default_branch = upstream.default_branch
    _run(["git", "checkout", "-B", branch, f"origin/{default_branch}"], cwd=local)

    for rel_path, content in file_rewrites.items():
        full_path = _safe_repo_path(local, rel_path)
        if full_path is None:
            raise ValueError(f"Invalid rewrite path: {rel_path}")
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content)

    modified = _run(["git", "status", "--short"], cwd=local)
    if not modified.strip():
        raise RuntimeError("No files were changed — feature patch produced no diff")

    _run(["git", "add", "-A"], cwd=local)
    commit_msg = f"{pr_title}\n\nFeature for {repo_full_name}\n\nGenerated by Patchwork"
    _run(["git", "commit", "-m", commit_msg], cwd=local)

    _run(["git", "push", "fork", branch, "--force"], cwd=local)

    pr = await asyncio.to_thread(
        _open_github_pr,
        upstream, fork, branch, default_branch, pr_title, pr_body
    )

    return {
        "pr_url": pr.html_url,
        "pr_number": pr.number,
        "branch": branch,
        "preflight": preflight,
    }
