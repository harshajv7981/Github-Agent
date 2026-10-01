# 🗺️ Patchwork Roadmap

This document outlines the strategic priorities and planned features for Patchwork, focusing heavily on contribution precision, AI agent context, and safe scale.

## 🚀 Priority 1: Container-Level Sandbox Security
While Patchwork currently implements process-level isolation (memory caps, credential scrubbing, output limits), running fully untrusted arbitrary code safely requires hypervisor or container boundaries.
* **Planned Improvements:** 
  * Migrate from local `/tmp/` worktrees to ephemeral Docker containers or isolated microVMs (e.g., Firecracker).
  * Strict networking restrictions (allow-list only package managers).
  * Enforced CPU and PID limits via cgroups.

## 🧠 Priority 2: Improve Code Correctness
Passing syntax checks and existing unit tests does not guarantee the patch actually resolves the user's issue conceptually.
* **Planned Improvements:**
  * **Issue-to-Acceptance-Criteria Agent:** Convert abstract issues into explicit acceptance criteria, map criteria to code paths, and identify missing context.
  * **Regression Test Generator:** Generate targeted tests specifically for the behavior being patched to prevent regressions.
  * **Final Diff Reviewer:** Run a dedicated "Reviewer AI" over the final patch payload before user approval.

## 🎯 Priority 3: High-Precision Issue Selection
Patchwork currently scores generic suitability. The goal is to aggressively filter out issues that are dead, un-actionable, or heavily contested.
* **Planned Improvements:**
  * Detect if an issue is already being actively worked on via PR references, external forks, and conversation velocity. *(Partially implemented via PR pre-flight checks).*
  * Identify requests that require maintainer design-approval before coding.
  * Deep analysis of recent commits and repository contribution guidelines *(CLA and template detection implemented).*

## 🔄 Priority 4: Closed-Loop PR Feedback
Currently, once Patchwork opens a PR, human maintainer feedback and native CI failures must be handled manually. 
* **Planned Improvements:**
  * **CI Failure Repair Agent:** Fetch GitHub Actions test logs, identify discrepancies between the Sandbox and CI environments, and propose automated fixes.
  * Classify maintainer reviews into code changes, clarifying questions, and hard rejections.
  * Propose automated follow-up commits for requested changes.

---

## 🔮 Six Targeted Feature Additions

### 1. AI PR Reviewer (High Priority)
An independent agent pass that reviews generated patches for logic errors, security flaws, unnecessary changes (enforcing the *Ponytail* guidelines), and missing tests prior to the human-in-the-loop approval step.

### 2. Repository Knowledge Graph (High Priority)
Map modules, functions, dependencies, tests, and call relationships into a queryable AST graph. This ensures the agent understands global blast-radius instead of just isolated files when making modifications.

### 3. CI Failure Repair Agent
Read GitHub Actions failures directly from the remote repository, identify likely causes, propose a fix, and rerun the appropriate tests in the isolated environment.

### 4. Issue-to-Acceptance-Criteria Agent (High Priority)
Sit sequentially before the code-generation step. Convert an issue into explicit bullet points, identify missing information, and map each criterion to a file before writing any code.

### 5. Contribution Learning Engine
A feedback loop that learns from Patchwork's own history of accepted, rejected, merged, and abandoned PRs (recorded in the `pull_requests` table telemetry) telemetry to continuously tweak issue selection fitness algorithms.

### 6. Regression Test Generator
Generate targeted tests for the specific behavior being changed. Especially critical when contributing to legacy repositories with limited pre-existing code coverage around the affected area.
