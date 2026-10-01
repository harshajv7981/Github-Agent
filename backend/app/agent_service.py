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
import subprocess
import textwrap
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from github import Github, GithubException
from ollama import AsyncClient


OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:9b")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

REPOS_CACHE_DIR = Path.home() / ".patchwork" / "repos"
MAX_FILE_CHARS = 6000   # chars sent to Ollama per file (keeps context manageable)
MAX_FILES = 4           # max files sent in one analysis prompt


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _run(cmd: list[str], cwd: Optional[Path] = None, check: bool = True) -> str:
    result = subprocess.run(
        cmd, cwd=str(cwd) if cwd else None,
        capture_output=True, text=True
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


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


async def generate_acceptance_criteria(
    repo_full_name: str,
    issue_number: int,
    issue_title: str,
    issue_body: str,
) -> dict:
    """
    Convert a GitHub issue into explicit, testable acceptance criteria,
    and flag if the issue is too ambiguous.
    """
    client = AsyncClient(host=OLLAMA_HOST)
    
    prompt = textwrap.dedent(f"""
        You are a principal engineer. Convert this GitHub issue into explicit, testable acceptance criteria before code is written.

        Repository: {repo_full_name}
        Issue #{issue_number}: {issue_title}
        Description: {(issue_body or '(no description)')[:1500]}

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
        model=OLLAMA_MODEL,
        prompt=prompt,
        think=False,
        options={"temperature": 0.1, "num_predict": 1024},
    )
    
    return _extract_json_block(resp.response)


async def analyze_issue(
    repo_full_name: str,
    issue_number: int,
    issue_title: str,
    issue_body: str,
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
    client = AsyncClient(host=OLLAMA_HOST)

    # 1. Clone / update the repo
    local = await asyncio.to_thread(_clone_or_update, repo_full_name)
    file_tree = await asyncio.to_thread(_repo_file_tree, local)


    # 1.5. Convert Issue to Acceptance Criteria
    ac_data = await generate_acceptance_criteria(repo_full_name, issue_number, issue_title, issue_body)
    acceptance_criteria = ac_data.get("criteria", [])
    ac_text = "- " + "\n- ".join(acceptance_criteria) if acceptance_criteria else "(None generated)"

    # 2. Ask Ollama which files are relevant
    file_selection_prompt = textwrap.dedent(f"""
        You are an expert software engineer reviewing a GitHub issue.

        Repository: {repo_full_name}
        Issue #{issue_number}: {issue_title}

        Issue description:
        {(issue_body or '(no description)')[:1500]}

        Acceptance Criteria:
        {ac_text}

        Here are the Python files in the repository:
        {file_tree}

        Based on the issue title and description, list up to {MAX_FILES} file paths
        that are most likely to need changes to fix this issue.

        Respond with ONLY a JSON object like:
        {{"files": ["path/to/file1.py", "path/to/file2.py"]}}

        Do NOT include test files unless the issue is about tests.
        Do NOT include __init__.py unless there's a strong reason.
    """).strip()

    selection_resp = await client.generate(
        model=OLLAMA_MODEL,
        prompt=file_selection_prompt,
        think=False,
        options={"temperature": 0.1, "num_predict": 512},
    )
    selection_data = _extract_json_block(selection_resp.response)
    relevant_files: list[str] = selection_data.get("files", [])[:MAX_FILES]

    # 3. Read the relevant files
    file_contents: dict[str, str] = {}
    for rel_path in relevant_files:
        content = await asyncio.to_thread(_read_file, local, rel_path)
        if content:
            file_contents[rel_path] = content

    if not file_contents:
        # fall back: just use the file tree as context
        file_contents = {"(no specific file selected)": file_tree[:3000]}

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

    fix_resp = await client.generate(
        model=OLLAMA_MODEL,
        prompt=fix_prompt,
        think=False,
        system="You are an expert open-source maintainer. Provide exact code rewrites in the requested === FILE: ... === format followed by the ANALYSIS and PR TITLE sections. Do not include thinking tokens.",
        options={"temperature": 0.2, "num_predict": 4096},
    )
    raw = fix_resp.response

    # 5. Parse response
    file_rewrites = _parse_file_rewrites(raw)

    cleaned_raw = re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=re.IGNORECASE).strip()

    # Extract ANALYSIS section
    analysis_match = re.search(r"ANALYSIS:([\s\S]+?)(?:PR TITLE:|$)", cleaned_raw or raw, re.IGNORECASE)
    analysis_text = analysis_match.group(1).strip() if analysis_match else (cleaned_raw or raw)[-1500:]

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
    client = AsyncClient(host=OLLAMA_HOST)

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
        model=OLLAMA_MODEL,
        prompt=prompt,
        think=False,
        options={"temperature": 0.1, "num_predict": 2048},
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
    preflight = gh_svc.run_pr_preflight(repo_full_name, branch, issue_number)
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
        raise RuntimeError("No files were changed — patch produced no diff")

    _run(["git", "add", "-A"], cwd=local)
    commit_msg = f"{pr_title}\n\nFixes #{issue_number} in {repo_full_name}\n\nGenerated by Patchwork"
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


def _get_or_create_fork(user, upstream):
    try:
        return user.get_repo(upstream.name)
    except GithubException:
        return user.create_fork(upstream)


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


async def suggest_features_for_repo(
    repo_full_name: str,
    repo_description: str = "",
) -> list[dict]:
    """
    Clone repo, read README/config and file tree, ask Ollama to suggest 3-5 concrete feature proposals.
    """
    client = AsyncClient(host=OLLAMA_HOST)
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
        model=OLLAMA_MODEL,
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
    client = AsyncClient(host=OLLAMA_HOST)
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
            model=OLLAMA_MODEL,
            prompt=selection_prompt,
            think=False,
            options={"temperature": 0.1, "num_predict": 512},
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
        model=OLLAMA_MODEL,
        prompt=impl_prompt,
        think=False,
        system="You are an expert open-source maintainer implementing a feature. Output full file rewrites in === FILE: ... === format, followed by ANALYSIS and PR TITLE. Do not include thinking tokens.",
        options={"temperature": 0.2, "num_predict": 4096},
    )
    raw = impl_resp.response

    file_rewrites = _parse_file_rewrites(raw)
    cleaned_raw = re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=re.IGNORECASE).strip()
    analysis_match = re.search(r"ANALYSIS:([\s\S]+?)(?:PR TITLE:|$)", cleaned_raw or raw, re.IGNORECASE)
    analysis_text = analysis_match.group(1).strip() if analysis_match else (cleaned_raw or raw)[-1500:]

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
