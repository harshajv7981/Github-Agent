# 🧵 Patchwork: Autonomous AI Open-Source Contribution Platform

> **Patchwork** is a local-first, autonomous AI engineer and contribution workspace powered by local LLMs (Ollama `qwen3.5:9b`), FastAPI, PostgreSQL, and React. It autonomously discovers high-impact open-source repositories, triages issues, proactively ideates architectural enhancements, generates multi-file code implementations, executes them inside an **isolated test sandbox** with automated quality checks (`pytest`, `flake8`, `mypy`), self-heals failing tests using AI diagnostics (capped at 3 attempts), and dispatches pull requests to GitHub after pre-flight duplicate and policy checks.

---

## 🌟 Core Features & Capabilities

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                   PATCHWORK WORKSPACE                                  │
├───────────────────────┬──────────────────────────┬─────────────────────────────────────┤
│  🔭 Autonomous        │  💡 Proactive AI         │  🧪 Isolated Test                   │
│     Discovery         │     Feature Ideation     │     Sandbox                         │
│  - 5k-50k star repos  │  - Architectural audit   │  - Temporary worktree isolation     │
│  - Issue suitability  │  - Impact & complexity   │  - py_compile, flake8, mypy, pytest │
│  - Daily APScheduler  │  - Step-by-step plans    │  - Real-time diagnostic logs        │
├───────────────────────┼──────────────────────────┼─────────────────────────────────────┤
│  ✨ AI Self-Healing   │  📁 Multi-File Diff      │  🚀 GitHub Pull Request             │
│     Engine            │     Generation           │     Dispatch                        │
│  - Traceback parser   │  - Structured file blocks│  - Automated branch creation        │
│  - Ollama code repair │  - Syntax-highlighted UI │  - Multi-file atomic commits        │
│  - Auto-revalidation  │  - Instant file switching│  - Formatted PR bodies & badges     │
└───────────────────────┴──────────────────────────┴─────────────────────────────────────┘
```

### 1. 🔭 Autonomous Repository & Issue Discovery
- **Targeted Repository Discovery**: Scans GitHub for trending, high-quality repositories in the optimal contribution range (5,000–50,000 stars) using the GitHub Search API.
- **Fit Scoring (0–100)**: Evaluates star momentum, issue volume, activity recency, and language match to prioritize top repositories.
- **Issue Triage & Difficulty Classification**: Discovers open issues, categorizes them (`good_first_issue`, `intermediate`), and calculates suitability scores for autonomous contribution.
- **Background Scheduler**: Automated daily discovery runs at 9:00 AM IST via `APScheduler`, with one-click manual triggers from the dashboard.

### 2. 💡 Proactive Architectural Feature Ideation
- **Autonomous Repository Audits**: When a repository doesn't have labeled starter issues, Patchwork's AI agent analyzes the codebase structure, design patterns, and dependencies to propose high-value enhancements.
- **Structured Proposals**: Generates feature title, category (e.g., `Design Pattern`, `Optimization`, `Security`, `Feature`), complexity rating, impact score (0–100), step-by-step implementation plan, and target file lists.
- **One-Click Implementation**: Instantly generates full multi-file code rewrites for any approved proposal.

### 3. 📁 Multi-File Code Generation & Diff Inspector
- **Full Codeblock Parsing**: Generates complete, syntactically correct multi-file codebases using structured file blocks (`=== FILE: path === ... === END FILE ===`).
- **Interactive Diff Viewer**: Preview before/after file changes, switch between modified files, and inspect proposed changes prior to execution or pull request submission.

### 4. 🧪 Isolated Test Sandbox (Process & Worktree Isolation)
- **Safe Execution Environment**: Copies target repositories into an isolated temporary workspace (`/tmp/patchwork_sandbox_<uuid>`) without dirtying the local repository cache.
- **4-Stage Verification Suite**:
  1. ⚡ **Syntax Validation (`py_compile`)**: Instant compilation check across all modified Python files.
  2. 🧹 **Code Style & Linters (`flake8`)**: Style and syntax error detection with standard rules (`--max-line-length=120 --ignore=E501,W503,E203`).
  3. 🏷️ **Static Type Checking (`mypy`)**: Type mismatch detection with `--ignore-missing-imports`.
  4. 🧪 **Automated Unit Testing (`pytest`)**: Targeted test execution with `-q -o addopts="" --tb=short` and timeout defense.
- **Real-Time Report Card**: Live dashboard tab showing test counts, pass/fail status, execution duration, and formatted failure tracebacks.
- **Terminal Error Recovery**: `/api/sandbox/verify` accepts an optional shell-free `terminal_command` token list (for example, `["python", "-m", "pytest", "tests"]`); its exit code and output are captured and sent to the self-healing loop. Healing defaults to 10 attempts and can be changed with `OPENROUTER_HEAL_MAX_ATTEMPTS`.

### 5. AI Self-Healing Loop (Capped at 3 Attempts)
- **Automated Failure Diagnostics**: Ingests test failure tracebacks, compilation errors, and linter warnings from the sandbox.
- **Ollama AI Debugger**: Feeds diagnostic error logs and current code blocks back to Ollama (`qwen3.5:9b`) with `think=False` for fast diagnosis and repair.
- **Diff History Tracking**: Each heal attempt is recorded with its analysis and outcome. Prior attempts are included in the LLM prompt to prevent repeating the same failed fix.
- **Automatic Re-Validation**: After each heal, reruns the complete 4-stage sandbox verification suite. Stops when all checks pass or the retry cap (default 3) is exhausted.
- **Graceful Failure**: When the cap is reached without success, returns `healed=False` with the full diff history for manual review.

### 6. 🚀 GitHub Pull Request Dispatch
- **Branch & Commit Automation**: Creates dedicated Git branches (e.g., `patchwork/feature-...` or `patchwork/fix-issue-...`), applies multi-file commits, and pushes them to GitHub.
- **Structured PR Documentation**: Generates comprehensive pull request titles, issue reference links, architectural summaries, and sandbox verification badges.
- **PR Lifecycle Tracking**: Monitors pull requests directly from the dashboard across states (`pending_review`, `merged`, `closed`, `rejected`).

### 7. 💻 Modern React Developer Dashboard
- **5 Dedicated Workspace Tabs**:
  - **🔭 Discover Repos**: Search, language filters, fit score badges, "Suggest Ideas" and "Find Issues" actions.
  - **💡 Feature Ideas**: Proactive feature proposals with impact scores, complexity badges, implementation modals, code generation, and sandbox testing.
  - **🐛 Candidate Issues**: GitHub issues ranked by suitability, AI issue analysis, and one-click fix generation.
  - **🚀 Pull Requests**: Dispatched and pending PRs with branch links, patch previews, and sandbox statuses.
  - **⚡ Runs & History**: Discovery run timeline, repositories scanned, and issues found.
- **Live Health Status Bar**: Real-time status indicators for FastAPI Backend, PostgreSQL database, Ollama LLM, and GitHub API authentication.

---

## 🏗️ System Architecture

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                               React 19 + Vite Dashboard                                │
│                     (Port 5173 • Dark Mode • Lucide Icons • Tailwind)                  │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │ HTTP / JSON REST API
┌───────────────────────────────────────────▼────────────────────────────────────────────┐
│                                FastAPI Backend Service                                 │
│                                      (Port 8000)                                       │
├─────────────────────┬──────────────────────┬────────────────────┬──────────────────────┤
│  github_service.py  │   agent_service.py   │ sandbox_service.py │     scheduler.py     │
│  - Repo discovery   │  - Feature ideation  │ - Worktree copy    │  - APScheduler       │
│  - Issue fetching   │  - Multi-file diffs  │ - py_compile check │  - Daily 9 AM IST    │
│  - PR creation      │  - Ollama generation │ - flake8 / mypy    │  - Manual triggers   │
│  - Branch & commit  │  - Context retrieval │ - pytest execution │  - Run tracking      │
└──────────┬──────────┴──────────┬───────────┴──────────┬─────────┴──────────┬───────────┘
           │                     │                      │                    │
           ▼                     ▼                      ▼                    ▼
   ┌───────────────┐     ┌───────────────┐      ┌───────────────┐    ┌───────────────┐
   │  GitHub REST  │     │  Ollama LLM   │      │ Isolated Temp │    │  PostgreSQL   │
   │      API      │     │  (qwen3.5:9b) │      │  Workspaces   │    │  (SQLAlchemy) │
   └───────────────┘     └───────────────┘      └───────────────┘    └───────────────┘
```

---

## 📂 Repository Structure

```
Github-Agent/
├── backend/
│   └── app/
│       ├── main.py              # FastAPI application, route handlers, Pydantic schemas
│       ├── models.py            # SQLAlchemy database models (Repository, Issue, Feature, PR, Run)
│       ├── database.py          # PostgreSQL async engine and session management
│       ├── agent_service.py     # AI agent for feature ideation, code diff generation, and repo analysis
│       ├── sandbox_service.py   # Isolated workspace runner, pytest/linters execution & AI self-healing
│       ├── github_service.py    # GitHub REST API client for repos, issues, and PR dispatch
│       └── scheduler.py         # Autonomous discovery orchestration & APScheduler jobs
├── frontend/
│   ├── src/
│   │   ├── App.tsx              # Full dashboard UI with 5 tabs, modals, and Sandbox Report Card
│   │   ├── App.css              # Custom dark-theme styling, glassmorphism, and sandbox components
│   │   └── main.tsx             # React DOM entry point
│   ├── package.json             # Frontend dependencies (React 19, Lucide icons, Vite)
│   └── vite.config.ts           # Vite configuration
├── requirements.txt             # Python backend dependencies
├── .env                         # Environment configuration (GitHub token, Ollama, Database URL)
├── setup.sh                     # Automated environment setup script
└── README.md                    # Project documentation
```

---

## 🛠️ API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | System health check (Database, Ollama LLM, GitHub token status) |
| `GET` | `/api/repositories` | Retrieve all discovered repositories with fit scores and stats |
| `GET` | `/api/issues` | List candidate GitHub issues with suitability ratings |
| `GET` | `/api/issues/{id}/acceptance-score` | Estimate maintainer acceptance likelihood |
| `POST` | `/api/issues/{id}/regression-test` | Generate and run a pre-patch regression test |
| `GET` | `/api/issues/{id}/trajectory` | View persisted agent events for an issue |
| `GET` | `/api/features` | List proactive feature suggestions generated by AI |
| `GET` | `/api/pull-requests` | List pull requests with review status and sandbox results |
| `GET` | `/api/pull-requests/{id}/ci-status` | Read the latest GitHub check-run status |
| `GET` | `/api/runs` | Discovery execution history and metrics |
| `GET` | `/api/repositories/{repo_full_name}/intelligence` | Build an AST-backed repository graph |
| `GET/PUT` | `/api/repositories/{repo_full_name}/memory` | Read or update repository contribution memory |
| `POST` | `/api/discovery/trigger` | Manually trigger a repository and issue discovery scan |
| `POST` | `/api/repositories/{repo_full_name}/suggest-features` | Proactively generate feature ideas for a specific repository |
| `POST` | `/api/features/{id}/implement` | Generate multi-file code rewrites for a feature proposal |
| `POST` | `/api/features/{id}/sandbox-verify` | Execute syntax checks, linters, and pytest on feature code |
| `POST` | `/api/features/{id}/create-pr` | Dispatch a verified feature pull request to GitHub |
| `POST` | `/api/issues/{id}/sandbox-verify` | Execute sandbox validation on an issue fix patch |
| `POST` | `/api/sandbox/verify` | Generic sandbox verification for arbitrary file rewrites |
| `POST` | `/api/sandbox/auto-heal` | Submit test failures to Ollama for automated code repair |
| `POST` | `/api/webhooks/github` | Receive signed GitHub issue, review, and CI events |

---

## 🚀 Quick Start Guide

### Prerequisites
- **Python 3.10+**
- **Node.js 20+**
- **PostgreSQL** running locally
- **Ollama** running locally with `qwen3.5:9b` or `qwen2.5-coder:7b`
- **GitHub Personal Access Token** (a classic PAT with `repo` scope is the most compatible option for fork-based PR creation; fine-grained PATs may authenticate successfully but still be unable to create forks)

### 1. Configure Environment Variables
Create a `.env` file in the project root:

```env
GITHUB_TOKEN=ghp_your_personal_access_token_here
DATABASE_URL=postgresql+asyncpg://chintugoddanti@localhost:5432/patchwork
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3.5:9b
OLLAMA_CODING_MODEL=qwen3.5:9b
OLLAMA_REVIEW_MODEL=qwen3.5:9b
LLM_PROVIDER=ollama
OPENROUTER_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free
OPENROUTER_API_KEY=
GROQ_MODEL=openai/gpt-oss-120b
GROQ_API_KEY=
GROQ_REASONING_EFFORT=medium
SANDBOX_RUNTIME=process
SANDBOX_DOCKER_IMAGE=patchwork-sandbox:latest
GITHUB_WEBHOOK_SECRET=replace_with_a_random_secret
```

To use OpenRouter instead of Ollama, set `LLM_PROVIDER=openrouter`, create a replacement OpenRouter key, and put it in `OPENROUTER_API_KEY`. The default OpenRouter model is `nvidia/nemotron-3-ultra-550b-a55b:free`; Ollama remains available with `LLM_PROVIDER=ollama`. Restart the backend after changing `.env`. Do not commit API keys or use the previously exposed key.

To use Groq instead, set `LLM_PROVIDER=groq`, put your key in `GROQ_API_KEY`, and use `GROQ_MODEL=openai/gpt-oss-120b` (the default). `GROQ_REASONING_EFFORT=medium` is used by default and can be set to `none` for models that do not support reasoning. Restart the backend after changing `.env`.

### Agent Workflow API

Patchwork's durable contribution agent can select work autonomously or run a specific issue:

```text
POST /api/agent-runs/next
   -> acceptance criteria -> failing regression test -> patch -> sandbox -> independent review
   -> approval -> PR -> CI monitoring -> approval-gated follow-up repair
```

Useful endpoints:

- `POST /api/agent-runs` starts a workflow for a specific `issue_id`.
- `POST /api/agent-runs/next` selects the highest-ranked unclaimed actionable issue.
- `GET /api/agent-runs/{id}` reads durable state and budget usage.
- `GET /api/agent-runs/{id}/steps` reads persisted checkpoints and tool results.
- `POST /api/agent-runs/{id}/resume` resumes a failed or queued run.
- `POST /api/agent-runs/{id}/approve-pr` creates a PR after human approval.
- `POST /api/pull-requests/{id}/ci-repair` proposes a repair from failed CI logs.
- `POST /api/pull-requests/{id}/ci-repair/approve` commits an approved follow-up.

Generated patches are limited to 20 files and 250,000 characters. Test execution, PR creation, and CI follow-up commits are approval-gated. Groq requests that exceed the account token-per-minute limit are retried with smaller completions and lower reasoning effort.

If PR creation reports `403 Resource not accessible by personal access token` while creating a fork, create the fork manually from the target repository's GitHub **Fork** button and retry. Patchwork will reuse an existing fork. Otherwise replace the token with a classic PAT that has the `repo` scope and authorize it for the target repository.

### 2. Start Ollama
Ensure your local Ollama instance is active and has the required model:

```bash
ollama serve
ollama pull qwen3.5:9b
```

### 3. Start the Backend API

```bash
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000 --reload
```

The FastAPI backend will be available at **`http://localhost:8000`** (Interactive Swagger documentation at **`http://localhost:8000/docs`**).

### 4. Start the Frontend Dashboard

In a separate terminal:

```bash
cd frontend
npm install
npm run dev
```

The React dashboard will be live at **`http://localhost:5173`**.

---

## 🧪 End-to-End Workflow Walkthrough

1. **Discover Repositories**:
   - Open `http://localhost:5173` and click **"Run Discovery"** or browse the 50+ automatically discovered Python repositories.
2. **Proactive Feature Ideation**:
   - On any repository card (e.g., `faif/python-patterns`), click **"Suggest Ideas"**.
   - Switch to the **"Feature Ideas"** tab to view generated architectural proposals with impact and complexity ratings.
3. **Generate Code Implementation**:
   - Click a feature card to open the inspection modal.
   - Click **"Implement with Ollama"** to generate the multi-file code rewrites.
4. **Generate Regression Proof and Verify**:
   - Generate a focused test and confirm it fails against the unmodified repository.
   - Apply the proposed fix and confirm the same test passes.
5. **Run Isolated Sandbox Verification**:
   - Click **"🧪 Run Sandbox Tests"** to execute syntax validation, `flake8`, `mypy`, and `pytest` in an isolated temp environment.
   - Inspect the live report card for unit test results and linter tables.
6. **AI Self-Healing (if tests fail)**:
   - If an assertion or syntax error is found, click **"✨ Auto-Heal with AI"**.
   - Ollama analyzes the traceback, fixes the code, and re-validates the test suite.
7. **Dispatch Pull Request**:
   - Click **"Create Pull Request"** to automatically create the branch, commit the files, and open the PR on GitHub.
   - Monitor the submission in the **"Pull Requests"** tab.

---

## 🔒 Safety & Isolation Philosophy

- **Provider choice**: Ollama runs locally. OpenRouter sends prompts and repository context to a hosted model provider; use it only for repositories and code you are comfortable sharing under the provider's terms.
- **Selectable Sandbox Isolation**: Development defaults to process mode. Production can set `SANDBOX_RUNTIME=docker` and build `Dockerfile.sandbox` for a container with no network, read-only root filesystem, dropped capabilities, no-new-privileges, CPU/memory/PID limits, strict timeouts, and automatic cleanup.
  - **Credential Scrubbing**: `GITHUB_TOKEN`, `DATABASE_URL`, API keys, and any environment variable matching `TOKEN`, `SECRET`, `PASSWORD`, or `CREDENTIAL` patterns are stripped from the sandbox environment.
  - **Memory Limits**: `ulimit -v` caps sandbox process virtual memory at 512 MB on Linux/macOS.
  - **Output Caps**: stdout/stderr are truncated at 1 MB to prevent runaway output.
   - **Note**: Process mode is not suitable for untrusted code. Use Docker mode for production and verify the image before accepting external repositories.

Build the production sandbox image with:

```bash
docker build -f Dockerfile.sandbox -t patchwork-sandbox:latest .
```
- **PR Pre-Flight Checks**: Before creating any pull request, the system runs pre-flight validation:
  - **Duplicate Detection**: Checks for existing open/closed PRs targeting the same branch or referencing the same issue.
  - **Assignee Check**: Warns if the target issue is already assigned to another contributor.
  - **Contribution Policy**: Scans `CONTRIBUTING.md` for CLA requirements, "issue first" policies, or "no unsolicited PRs" language. Detects PR templates.
  - PRs are blocked on hard duplicate conflicts and surface warnings for soft conflicts.
- **Self-Healing Limits**: The AI auto-heal loop is capped at 3 attempts. Each attempt is tracked with diff history so the LLM avoids repeating failed fixes. The full verification suite reruns after each heal. If the cap is exhausted without passing, the system stops and reports manual review is required.
- **Contribution Quality Gates**: AI-proposed feature enhancements are flagged as `ai_proposed` and carry a review notice in the PR body. Maintainer-requested issue fixes (from GitHub issues) are prioritized over proactive proposals.
- **Human-in-the-Loop Review**: All code diffs, test logs, and PR proposals require explicit user inspection and approval before dispatching to GitHub.

---

## 🔄 Pull Request Lifecycle

| State | Description |
|---|---|
| `creating` | PR record created, git operations in progress |
| `open` | PR successfully opened on GitHub |
| `pending_review` | Awaiting maintainer review |
| `merged` | PR merged by maintainer |
| `closed` | PR closed without merge (may indicate rejection) |
| `failed` | PR creation failed (pre-flight block, git error, API failure) |

**Handling rejection and feedback:**
- If a PR is closed without merge, the pre-flight system flags the branch as previously rejected. Resubmitting to the same branch surfaces a warning.
- CI failures on the remote repository are visible in the dashboard's PR tab but are not automatically remediated — they require manual investigation since the CI environment may differ from the local sandbox.
- Requested changes from maintainers are tracked in the PR status but require manual response.

---


## 📊 Success Metrics & Telemetry

To measure whether Patchwork is producing genuinely useful contributions rather than just high volumes of PRs, the following telemetry targets are tracked (tracked via the `/api/telemetry` endpoint and viewable in the React Dashboard Metrics tab):

| Metric | What it tells you |
|---|---|
| **Issue selection precision** | How many autonomously selected issues were genuinely suitable without manual overrides. |
| **First-pass test success** | How often the AI's generated fixes pass the sandbox `pytest` and linters on the very first try. |
| **Repair success rate** | How often the AI self-healing loop successfully resolves failures before the retry cap. |
| **PR acceptance rate** | How many PRs receive meaningful, positive maintainer engagement (approvals, LGTMs). |
| **Merge rate** | How many PRs are ultimately merged by maintainers into the target repositories. |
| **Duplicate PR rate** | How often the agent attempts redundant contributions, blocked by pre-flight checks. |
| **Cost per successful contribution** | Local compute token usage (or API costs if scaled out) relative to accepted PRs. |
| **Time per contribution** | End-to-end duration from issue selection and sandbox testing to PR dispatch. |

---

## 📄 License
MIT License. Open-source and built for the developer community.
