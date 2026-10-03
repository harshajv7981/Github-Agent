"""
Agentic pipeline: analyze a GitHub issue, generate a patch via Ollama, create a PR.

Flow:
  1. analyze_issue() — clone repo, ask Ollama which files are relevant, read them,
     ask Ollama for a fix, return analysis + proposed file rewrites
  2. create_pull_request() — fork, branch, apply rewrites, push, open PR on GitHub
"""

import os
import re
import asyncio
import logging
import shutil
import subprocess
import textwrap
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from github import Github, GithubException
from app.llm_client import get_llm_client
from app.model_router import model_for, provider_name


GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

REPOS_CACHE_DIR = Path.home() / ".patchwork" / "repos"
logger = logging.getLogger(__name__)
MAX_FILE_CHARS = 6000   # chars sent to Ollama per file (keeps context manageable)
MAX_FILES = 4           # max files sent in one analysis prompt


def _json_options(options: dict) -> dict:
    if provider_name() == "groq":
        return {**options, "response_format": {"type": "json_object"}}
    return options


from app.agent_helpers import (
    MAX_FILES,
    REPOS_CACHE_DIR,
    _clean_analysis_text,
    _cleanup_repo_cache as _cleanup_repo_cache_impl,
    _clone_or_update,
    _extract_json_block,
    _parse_file_rewrites,
    _read_file,
    _repo_file_tree,
    _run,
    _safe_repo_path,
)


def _cleanup_repo_cache(repo_full_name: str) -> None:
    _cleanup_repo_cache_impl(repo_full_name, REPOS_CACHE_DIR)

# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


async def generate_acceptance_criteria(
    repo_full_name: str,
    issue_number: int,
    issue_title: str,
    issue_body: str,
    repository_memory: str = "",
) -> dict:
    """
    Convert a GitHub issue into explicit, testable acceptance criteria,
    and flag if the issue is too ambiguous.
    """
    client = get_llm_client()
    
    prompt = textwrap.dedent(f"""
        You are a principal engineer. Convert this GitHub issue into explicit, testable acceptance criteria before code is written.

        Repository: {repo_full_name}
        Issue #{issue_number}: {issue_title}
        Description: {(issue_body or '(no description)')[:1500]}

        Repository memory from prior contribution work:
        {repository_memory or '(none)'}

        Instructions:
        1. Extract the core requirements and expected behavior.
        2. Generate 3-5 explicit, testable acceptance criteria.
        3. Determine if the issue is actionable or too ambiguous (needs maintainer clarification).

        Ponytail "Lazy Senior Dev" Guidelines:
        - Do not over-specify or invent requirements that aren't asked for.
        - Be highly pragmatic and brief.
        
        Respond ONLY with a JSON object format:
        {{
            "criteria": ["criterion 1", "criterion 2"],
            "is_actionable": true,
            "missing_context": "Any clarifying questions to ask (or null if clear)"
        }}
    """).strip()

    resp = await client.generate(
        model=model_for("triage"),
        prompt=prompt,
        think=False,
        options=_json_options({"temperature": 0.1, "num_predict": 1024}),
    )
    
    return _extract_json_block(resp.response)


async def analyze_issue(
    repo_full_name: str,
    issue_number: int,
    issue_title: str,
    issue_body: str,
    repository_memory: str = "",
) -> dict:
    """
    Clone the repo, ask Ollama which files are relevant, read them,
    ask Ollama to produce a fix.

    Returns:
        {
            "analysis": str,       # human-readable analysis
            "file_rewrites": {     # path -> new full file content
                "src/foo.py": "...",
            },
            "pr_title": str,
            "pr_body": str,
            "relevant_files": [str],
        }
    """
    client = get_llm_client()
    logger.info(
        "Issue analysis started repo=%s issue=%s provider=%s",
        repo_full_name,
        issue_number,
        os.getenv("LLM_PROVIDER", "ollama"),
    )

    # 1. Clone / update the repo
    stage_started = time.perf_counter()
    logger.info("Issue analysis cloning repository repo=%s issue=%s", repo_full_name, issue_number)
    local = await asyncio.to_thread(_clone_or_update, repo_full_name)
    file_tree = await asyncio.to_thread(_repo_file_tree, local)
    logger.info(
        "Issue analysis repository ready repo=%s issue=%s python_files=%d duration_seconds=%.2f",
        repo_full_name,
        issue_number,
        len(file_tree.splitlines()) if file_tree else 0,
        time.perf_counter() - stage_started,
    )


    # 1.5. Convert Issue to Acceptance Criteria
    stage_started = time.perf_counter()
    logger.info("Issue analysis generating acceptance criteria repo=%s issue=%s", repo_full_name, issue_number)
    ac_data = await generate_acceptance_criteria(
        repo_full_name, issue_number, issue_title, issue_body, repository_memory
    )
    acceptance_criteria = ac_data.get("criteria", [])
    ac_text = "- " + "\n- ".join(acceptance_criteria) if acceptance_criteria else "(None generated)"
    logger.info(
        "Issue analysis acceptance criteria ready repo=%s issue=%s count=%d duration_seconds=%.2f",
        repo_full_name,
        issue_number,
        len(acceptance_criteria),
        time.perf_counter() - stage_started,
    )

    # 2. Ask Ollama which files are relevant
    file_selection_prompt = textwrap.dedent(f"""
        You are an expert software engineer reviewing a GitHub issue.

        Repository: {repo_full_name}

        Issue description:
        {(issue_body or '(no description)')[:1500]}

        Acceptance Criteria:
        {ac_text}

        Repository memory from prior contribution work:
        {repository_memory or '(none)'}

        Here are the Python files in the repository:
        {file_tree}

        Based on the issue title and description, list up to {MAX_FILES} file paths
        that are most likely to need changes to fix this issue.

        Respond with ONLY a JSON object like:
        {{"files": ["path/to/file1.py", "path/to/file2.py"]}}

        Do NOT include test files unless the issue is about tests.
        Do NOT include __init__.py unless there's a strong reason.
    """).strip()

    stage_started = time.perf_counter()
    logger.info("Issue analysis selecting relevant files repo=%s issue=%s", repo_full_name, issue_number)
    selection_resp = await client.generate(
        model=model_for("triage"),
        prompt=file_selection_prompt,
        think=False,
        options=_json_options({"temperature": 0.1, "num_predict": 512}),
    )
    selection_data = _extract_json_block(selection_resp.response)
    relevant_files: list[str] = selection_data.get("files", [])[:MAX_FILES]
    logger.info(
        "Issue analysis file selection complete repo=%s issue=%s selected_files=%d duration_seconds=%.2f",
        repo_full_name,
        issue_number,
        len(relevant_files),
        time.perf_counter() - stage_started,
    )

    # 3. Read the relevant files
    file_contents: dict[str, str] = {}
    for rel_path in relevant_files:
        content = await asyncio.to_thread(_read_file, local, rel_path)
        if content:
            file_contents[rel_path] = content

    if not file_contents:
        # fall back: just use the file tree as context
        file_contents = {"(no specific file selected)": file_tree[:3000]}
    logger.info(
        "Issue analysis context ready repo=%s issue=%s files_read=%d",
        repo_full_name,
        issue_number,
        len(file_contents),
    )

    files_block = "\n\n".join(
        f"### {path}\n```python\n{content}\n```"
        for path, content in file_contents.items()
    )

    # 4. Ask Ollama for the fix
    fix_prompt = textwrap.dedent(f"""
        You are a senior open-source contributor. Fix or implement the following GitHub issue.

        Repository: {repo_full_name}
        Issue #{issue_number}: {issue_title}

        Issue description:
        {(issue_body or '(no description)')[:1500]}

        Acceptance Criteria:
        {ac_text}

        Repository memory from prior contribution work:
        {repository_memory or '(none)'}

        Relevant source files:
        {files_block}

        Instructions:
        - Make MINIMAL, focused changes that address the issue.
        - Match the existing code style exactly.
        - For every file you change, output the COMPLETE new file content (not a diff).

        Ponytail "Lazy Senior Dev" Guidelines:
        - YAGNI (You Aren't Gonna Need It): Do not build things unless explicitly required.
        - Reuse existing codebase helpers, utils, and standard library features before writing new code.
        - Delete over addition. Ensure the shortest, simplest working diff.
        - No unrequested boilerplate or premature abstractions.
        - Fix root causes (shared functions), not just symptoms (call locations).
        - Maintain strict security, error handling, and trust boundary validations (do not be lazy about correctness).
        - Format each changed file EXACTLY like this:

        === FILE: path/to/file.py ===
        <complete new file content here>
        === END FILE ===

        After all file blocks, write a short section called ANALYSIS: with:
        - What the root cause of the issue is (2-3 sentences)
        - What you changed and why (2-3 sentences)
        - Suggested PR title (one line, prefixed "PR TITLE:")
    """).strip()

    stage_started = time.perf_counter()
    logger.info("Issue analysis generating proposed fix repo=%s issue=%s", repo_full_name, issue_number)
    fix_resp = await client.generate(
        model=model_for("coding"),
        prompt=fix_prompt,
        think=False,
        system="You are an expert open-source maintainer. Provide exact code rewrites in the requested === FILE: ... === format followed by the ANALYSIS and PR TITLE sections. Do not include thinking tokens.",
        options={"temperature": 0.2, "num_predict": 4096},
    )
    raw = fix_resp.response
    logger.info(
        "Issue analysis proposed fix received repo=%s issue=%s response_chars=%d duration_seconds=%.2f",
        repo_full_name,
        issue_number,
        len(raw),
        time.perf_counter() - stage_started,
    )

    # 5. Parse response
    file_rewrites = _parse_file_rewrites(raw)
    logger.info(
        "Issue analysis completed repo=%s issue=%s rewritten_files=%d relevant_files=%d",
        repo_full_name,
        issue_number,
        len(file_rewrites),
        len(file_contents),
    )

    cleaned_raw = re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=re.IGNORECASE).strip()

    # Extract ANALYSIS section
    analysis_match = re.search(r"ANALYSIS:([\s\S]+?)(?:PR TITLE:|$)", cleaned_raw or raw, re.IGNORECASE)
    analysis_text = _clean_analysis_text(raw, analysis_match)

    pr_title_match = re.search(r"PR TITLE:\s*(.+)", raw, re.IGNORECASE)
    pr_title = pr_title_match.group(1).strip() if pr_title_match else f"Fix: {issue_title}"
    pr_title = pr_title.strip('"\'')

    pr_body = textwrap.dedent(f"""
        Closes #{issue_number}

        ## What changed
        {analysis_text}

        ## How to test
        - Review the changed files
        - Run existing tests
        - Verify the behavior described in #{issue_number} is resolved

        ---
        *Generated by [Patchwork](https://github.com) — AI open-source contribution agent*
    """).strip()

    return {
        "analysis": analysis_text,
        "acceptance_criteria": acceptance_criteria,
        "is_actionable": ac_data.get("is_actionable", True),
        "file_rewrites": file_rewrites,
        "pr_title": pr_title,
        "pr_body": pr_body,
        "relevant_files": list(file_contents.keys()),
    }


async def generate_regression_test(
    repo_full_name: str,
    issue_number: int,
    issue_title: str,
    issue_body: str,
    feedback: str = "",
) -> dict:
    """Generate one focused regression test and return it for pre-patch validation."""
    client = get_llm_client()
    local = await asyncio.to_thread(_clone_or_update, repo_full_name)
    file_tree = await asyncio.to_thread(_repo_file_tree, local)

    prompt = textwrap.dedent(f"""
        You are writing a minimal regression test for a GitHub issue.

        Repository: {repo_full_name}
        Issue #{issue_number}: {issue_title}
        Description: {(issue_body or '(no description)')[:1800]}

        Feedback from a previous generated test attempt:
        {feedback or '(none; first attempt)'}

        Python source files:
        {file_tree}

        Write exactly one focused pytest test that expresses the missing behavior.
        The test must fail against the current repository if the issue is real and
        pass after a correct implementation. Do not test unrelated behavior.
        If the previous attempt passed on the current repository, choose a different
        public behavior or fixture that directly exercises the issue.
        Use only the repository's existing public APIs and standard pytest features.
        Return ONLY JSON in this format:
        {{
          "test_path": "tests/test_patchwork_regression.py",
          "test_content": "complete Python file content",
          "explanation": "what behavior this test proves"
        }}
    """).strip()

    response = await client.generate(
        model=model_for("review"),
        prompt=prompt,
        think=False,
        options=_json_options({"temperature": 0.1, "num_predict": 3072}),
    )
    data = _extract_json_block(response.response)
    if not isinstance(data, dict):
        raise ValueError("Ollama did not return a regression test object")

    test_path = str(data.get("test_path", "tests/test_patchwork_regression.py")).strip()
    test_content = str(data.get("test_content", ""))
    safe_path = _safe_repo_path(local, test_path)
    if safe_path is None or not test_path.startswith("tests/") or not test_path.endswith(".py"):
        raise ValueError("Generated regression test must be a Python file under tests/")
    if not test_content.strip():
        raise ValueError("Generated regression test is empty")

    return {
        "test_path": test_path,
        "test_content": test_content,
        "explanation": str(data.get("explanation", "Regression test for the reported issue.")),
    }



async def review_patch(
    repo_full_name: str,
    issue_title: str,
    issue_body: str,
    acceptance_criteria: list[str],
    file_rewrites: dict[str, str],
    sandbox_result: dict | None,
) -> dict:
    """
    Act as an independent Senior AI Code Reviewer.
    Assess whether the generated fix satisfies acceptance criteria, is safe, and
    follows Ponytail guidelines.
    """
    client = get_llm_client()

    ac_text = "- " + "\n- ".join(acceptance_criteria) if acceptance_criteria else "(No Acceptance Criteria provided)"
    
    files_block = "\n\n".join(
        f"### {path}\n```python\n{content}\n```"
        for path, content in (file_rewrites or {}).items()
    )

    import json
    sandbox_text = json.dumps(sandbox_result, indent=2) if sandbox_result else "(No sandbox results available)"

    prompt = textwrap.dedent(f"""
        You are a strict, independent Principal Security and Code Reviewer.
        Evaluate the proposed patch for a GitHub issue in the repository.

        Repository: {repo_full_name}
        Issue: {issue_title}
        Description: {(issue_body or '(no description)')[:1000]}

        Acceptance Criteria:
        {ac_text}

        Proposed File Changes (Full replacements):
        {files_block}

        Sandbox Test Results (Linters & Pytest):
        {sandbox_text}

        Repository memory from prior contribution work:
        {repository_memory or '(none)'}

        Instructions:
        1. Check correctness: Does the patch actually solve the issue?
        2. Check against Acceptance Criteria: Are ALL criteria satisfied?
        3. Check security risks & error handling.
        4. Check for unnecessary changes (Ponytail principle: YAGNI, minimal diff).
        5. Are tests missing for new behavior?

        Respond ONLY with a JSON object in this exact format:
        {{
            "decision": "PASS" | "NEEDS_REVISION" | "BLOCKED",
            "summary": "1-2 sentence overall review",
            "findings": [
                {{
                    "severity": "high" | "medium" | "low",
                    "file_path": "path/to/file",
                    "explanation": "Why this is an issue",
                    "suggested_fix": "How to resolve it (optional)"
                }}
            ]
        }}
    """).strip()

    resp = await client.generate(
        model=model_for("coding"),
        prompt=prompt,
        think=False,
        options=_json_options({"temperature": 0.1, "num_predict": 2048}),
    )

    data = _extract_json_block(resp.response)
    
    # Normalization
    decision = str(data.get("decision", "NEEDS_REVISION")).upper()
    if decision not in ["PASS", "NEEDS_REVISION", "BLOCKED"]:
        decision = "NEEDS_REVISION"
        
    return {
        "decision": decision,
        "summary": str(data.get("summary", "Review complete.")),
        "findings": data.get("findings", [])
    }


async def create_pull_request(
    repo_full_name: str,
    issue_number: int,
    pr_title: str,
    pr_body: str,
    file_rewrites: dict[str, str],
) -> dict:
    """
    Apply the file rewrites in a fork of the repo and open a PR.
    Runs pre-flight checks for duplicates, assignees, and contribution policy.

    Returns:
        {"pr_url": str, "pr_number": int, "branch": str, "preflight": dict}
    """
    if not GITHUB_TOKEN:
        raise RuntimeError("GITHUB_TOKEN is not set — cannot create PR")

    branch = f"patchwork/fix-issue-{issue_number}"

    from app.github_service import GitHubService
    gh_svc = GitHubService(GITHUB_TOKEN)
    logger.info("PR creation preflight started repo=%s issue=%s", repo_full_name, issue_number)
    preflight = await asyncio.to_thread(
        gh_svc.run_pr_preflight, repo_full_name, branch, issue_number
    )
    if not preflight["ok"]:
        raise RuntimeError(
            f"PR pre-flight blocked: {'; '.join(preflight['blockers'])}"
        )

    logger.info("PR creation GitHub setup started repo=%s", repo_full_name)
    gh = Github(GITHUB_TOKEN, timeout=30)
    user, upstream = await asyncio.gather(
        asyncio.to_thread(gh.get_user),
        asyncio.to_thread(gh.get_repo, repo_full_name),
    )

    fork = await asyncio.to_thread(_get_or_create_fork, user, upstream)
    logger.info("PR creation fork ready repo=%s fork=%s", repo_full_name, fork.full_name)

    logger.info("PR creation clone started repo=%s", repo_full_name)
    local = await asyncio.to_thread(_clone_or_update, repo_full_name)
    logger.info("PR creation clone ready repo=%s", repo_full_name)
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
        raise RuntimeError("No files were changed — patch produced no diff")

    _run(["git", "add", "-A"], cwd=local)
    commit_msg = f"{pr_title}\n\nFixes #{issue_number} in {repo_full_name}\n\nGenerated by Patchwork"
    _run(["git", "commit", "-m", commit_msg], cwd=local)

    logger.info("PR creation pushing branch repo=%s branch=%s", repo_full_name, branch)
    _run(["git", "push", "fork", branch, "--force"], cwd=local)

    pr = await asyncio.to_thread(
        _open_github_pr,
        upstream, fork, branch, default_branch, pr_title, pr_body
    )
    logger.info("PR creation completed repo=%s pr=%s", repo_full_name, pr.number)

    _cleanup_repo_cache(repo_full_name)

    return {
        "pr_url": pr.html_url,
        "pr_number": pr.number,
        "branch": branch,
        "preflight": preflight,
    }


def _get_or_create_fork(user, upstream):
    try:
        return user.get_repo(upstream.name)
    except GithubException as error:
        if error.status != 404:
            raise RuntimeError(
                "GitHub authenticated successfully, but this token cannot access "
                f"the fork account or repository ({error.status}). Use a classic "
                "the upstream repository and fork creation, then retry."
            ) from error

    try:
        return user.create_fork(upstream)
    except GithubException as error:
        if error.status == 403:
            raise RuntimeError(
                "GitHub rejected fork creation (403). The PAT needs permission "
                "to create forks. For a classic PAT, enable the repo scope; for "
                "a fine-grained PAT, authorize the repository and use a token "
                "that supports fork creation. You can also create the fork "
                f"manually at https://github.com/{upstream.full_name}/fork."
            ) from error
        raise RuntimeError(f"GitHub could not create the fork: {error}") from error


def _open_github_pr(upstream, fork, branch, base_branch, pr_title, pr_body):
    head = f"{fork.owner.login}:{branch}"
    try:
        return upstream.create_pull(
            title=pr_title,
            body=pr_body,
            head=head,
            base=base_branch,
        )
    except GithubException as e:
        # PR may already exist
        if "already exists" in str(e).lower():
            for pr in upstream.get_pulls(state="open", head=head):
                return pr
        raise
