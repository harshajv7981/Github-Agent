import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional
from dotenv import load_dotenv
from github import Github, GithubException, Auth
from github.Repository import Repository as GithubRepo
from github.Issue import Issue as GithubIssue

load_dotenv(Path(__file__).parent.parent.parent / ".env")


class GitHubService:
    def __init__(self, access_token: Optional[str] = None):
        self.token = access_token or os.getenv("GITHUB_TOKEN")
        if self.token:
            self.client = Github(auth=Auth.Token(self.token))
        else:
            self.client = Github()

    async def discover_trending_repositories(
        self,
        language: str = "python",
        max_results: int = 50,
        min_stars: int = 5000,
        max_stars: int = 50000
    ) -> List[dict]:
        """Discover trending repositories based on recent star growth."""

        one_week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

        query = f"language:{language} stars:{min_stars}..{max_stars} pushed:>{one_week_ago}"

        try:
            repos = self.client.search_repositories(
                query=query,
                sort="stars",
                order="desc"
            )

            results = []
            count = 0
            for repo in repos:
                if count >= max_results:
                    break
                repo_data = self._extract_repo_data(repo)
                results.append(repo_data)
                count += 1

            return results

        except GithubException as e:
            print(f"GitHub API error: {e}")
            return []

    async def discover_popular_repositories(
        self,
        language: str = "python",
        max_results: int = 50,
        min_stars: int = 1000,
        max_stars: int = 30000
    ) -> List[dict]:
        """Discover most popular repositories by stars in contributor-friendly range."""

        query = f"language:{language} stars:{min_stars}..{max_stars} good-first-issues:>5"

        try:
            repos = self.client.search_repositories(
                query=query,
                sort="stars",
                order="desc"
            )

            results = []
            count = 0
            for repo in repos:
                if count >= max_results:
                    break
                repo_data = self._extract_repo_data(repo)
                results.append(repo_data)
                count += 1

            return results

        except GithubException as e:
            print(f"GitHub API error: {e}")
            return []

    async def find_suitable_issues(
        self,
        repo_full_name: str,
        labels: Optional[List[str]] = None
    ) -> List[dict]:
        """Find issues suitable for contribution in a repository."""

        if labels is None:
            labels = [
                "good first issue",
                "good-first-issue",
                "beginner",
                "help wanted",
                "enhancement",
                "bug"
            ]

        try:
            repo = self.client.get_repo(repo_full_name)

            issues = []
            seen_numbers: set[int] = set()
            for label_name in labels:
                try:
                    label_issues = repo.get_issues(
                        state="open",
                        labels=[label_name],
                        sort="updated",
                        direction="desc"
                    )

                    count = 0
                    for issue in label_issues:
                        if count >= 10:
                            break
                        if not issue.pull_request and issue.number not in seen_numbers:
                            seen_numbers.add(issue.number)
                            issue_data = self._extract_issue_data(issue, repo_full_name)
                            issues.append(issue_data)
                            count += 1

                except GithubException:
                    continue

            return issues

        except GithubException as e:
            print(f"Error fetching issues from {repo_full_name}: {e}")
            return []

    def get_open_issue_numbers(self, repo_full_name: str) -> set[int] | None:
        """Return current open issue numbers, or None when GitHub cannot be read."""
        try:
            repo = self.client.get_repo(repo_full_name)
            return {issue.number for issue in repo.get_issues(state="open") if not issue.pull_request}
        except GithubException as error:
            print(f"Error fetching open issue state from {repo_full_name}: {error}")
            return None

    def get_issue_state(self, repo_full_name: str, issue_number: int) -> str:
        """Read the authoritative current GitHub state for one issue."""
        repo = self.client.get_repo(repo_full_name)
        return str(repo.get_issue(issue_number).state).lower()

    def _extract_repo_data(self, repo: GithubRepo) -> dict:
        """Extract relevant data from a GitHub repository object."""

        owner, name = repo.full_name.split("/")

        trend_percent = self._calculate_trend(repo)
        fit_score = self._calculate_fit_score(repo)

        return {
            "full_name": repo.full_name,
            "owner": owner,
            "name": name,
            "description": repo.description or "",
            "language": repo.language or "Unknown",
            "stars": repo.stargazers_count,
            "open_issues": repo.open_issues_count,
            "fit_score": fit_score,
            "trend_percent": trend_percent,
            "url": repo.html_url,
            "last_scanned_at": datetime.utcnow()
        }

    def _extract_issue_data(self, issue: GithubIssue, repo_full_name: str) -> dict:
        """Extract relevant data from a GitHub issue object."""

        difficulty = self._determine_difficulty(issue)
        suitability_score = self._calculate_suitability_score(issue)

        labels = [label.name for label in issue.labels]
        primary_label = labels[0] if labels else "unlabeled"

        updated_at = issue.updated_at
        if updated_at is not None and updated_at.tzinfo is not None:
            updated_at = updated_at.replace(tzinfo=None)
        elif updated_at is None:
            updated_at = datetime.utcnow()

        return {
            "repository": repo_full_name,
            "title": issue.title,
            "number": issue.number,
            "label": primary_label,
            "difficulty": difficulty,
            "url": issue.html_url,
            "body": issue.body or "",
            "suitability_score": suitability_score,
            "is_suitable": suitability_score >= 60,
            "updated_at": updated_at
        }

    def _calculate_trend(self, repo: GithubRepo) -> int:
        """Calculate trend percentage based on recent activity."""

        try:
            days_since_update = (datetime.now() - repo.updated_at.replace(tzinfo=None)).days

            if days_since_update <= 1:
                return 20
            elif days_since_update <= 7:
                return 15
            elif days_since_update <= 30:
                return 10
            else:
                return 5
        except:
            return 5

    def _calculate_fit_score(self, repo: GithubRepo) -> int:
        """Calculate repository fit score (0-100)."""

        score = 50

        if repo.stargazers_count > 10000:
            score += 20
        elif repo.stargazers_count > 1000:
            score += 10

        if repo.open_issues_count > 0 and repo.open_issues_count < 100:
            score += 15
        elif repo.open_issues_count > 0:
            score += 5

        if repo.has_issues and not repo.archived:
            score += 10

        days_since_update = (datetime.now() - repo.updated_at.replace(tzinfo=None)).days
        if days_since_update <= 7:
            score += 10
        elif days_since_update <= 30:
            score += 5

        return min(score, 100)

    def _determine_difficulty(self, issue: GithubIssue) -> str:
        """Determine issue difficulty based on labels."""

        label_names = [label.name.lower() for label in issue.labels]

        good_first_issue_labels = [
            "good first issue",
            "good-first-issue",
            "beginner",
            "easy",
            "starter"
        ]

        for label in label_names:
            if any(gfi in label for gfi in good_first_issue_labels):
                return "good_first_issue"

        return "intermediate"

    def _calculate_suitability_score(self, issue: GithubIssue) -> int:
        """Calculate issue suitability score (0-100)."""

        score = 50

        if issue.comments == 0:
            score += 20
        elif issue.comments <= 3:
            score += 10

        label_names = [label.name.lower() for label in issue.labels]
        good_labels = ["good first issue", "help wanted", "documentation", "enhancement"]
        if any(gl in " ".join(label_names) for gl in good_labels):
            score += 15

        days_old = (datetime.now() - issue.created_at.replace(tzinfo=None)).days
        if 1 <= days_old <= 14:
            score += 10
        elif days_old <= 30:
            score += 5

        body_length = len(issue.body or "")
        if body_length > 100:
            score += 5

        return min(score, 100)

    def check_existing_prs(
        self,
        repo_full_name: str,
        branch_name: str,
        issue_number: Optional[int] = None,
    ) -> dict:
        """
        Pre-flight check for duplicate or conflicting PRs.

        Returns:
            {
                "has_duplicate": bool,
                "existing_prs": [{"number", "title", "url", "state", "head_branch"}],
                "issues": [str]  — human-readable blockers
            }
        """
        try:
            repo = self.client.get_repo(repo_full_name)
        except GithubException as e:
            return {"has_duplicate": False, "existing_prs": [], "issues": [f"Cannot access repo: {e}"]}

        issues_list: List[str] = []
        existing: List[dict] = []

        user = self.client.get_user()
        head_prefix = f"{user.login}:"

        for pr in repo.get_pulls(state="all"):
            if pr.head.ref == branch_name or (pr.head.label and pr.head.label.startswith(head_prefix) and pr.head.ref == branch_name):
                existing.append({
                    "number": pr.number,
                    "title": pr.title,
                    "url": pr.html_url,
                    "state": pr.state,
                    "head_branch": pr.head.ref,
                })
                if pr.state == "open":
                    issues_list.append(f"Open PR #{pr.number} already targets branch '{branch_name}'")
                elif pr.state == "closed" and not pr.merged:
                    issues_list.append(f"PR #{pr.number} on branch '{branch_name}' was closed without merge — submitting again may be unwelcome")

        if issue_number:
            for pr in repo.get_pulls(state="open"):
                body = pr.body or ""
                title = pr.title or ""
                if f"#{issue_number}" in body or f"#{issue_number}" in title:
                    if not any(e["number"] == pr.number for e in existing):
                        existing.append({
                            "number": pr.number,
                            "title": pr.title,
                            "url": pr.html_url,
                            "state": pr.state,
                            "head_branch": pr.head.ref,
                        })
                        issues_list.append(f"Open PR #{pr.number} already references issue #{issue_number}")

        return {
            "has_duplicate": len(issues_list) > 0,
            "existing_prs": existing,
            "issues": issues_list,
        }

    def check_issue_assignee(self, repo_full_name: str, issue_number: int) -> dict:
        """Check if an issue is already assigned to someone."""
        try:
            repo = self.client.get_repo(repo_full_name)
            issue = repo.get_issue(issue_number)
        except GithubException as e:
            return {"assigned": False, "assignees": [], "error": str(e)}

        assignees = [a.login for a in issue.assignees]
        return {
            "assigned": len(assignees) > 0,
            "assignees": assignees,
        }

    def check_contribution_policy(self, repo_full_name: str) -> dict:
        """Check for CONTRIBUTING.md and PR templates."""
        try:
            repo = self.client.get_repo(repo_full_name)
        except GithubException as e:
            return {"has_contributing": False, "has_pr_template": False, "notes": [str(e)]}

        notes: List[str] = []
        has_contributing = False
        contributing_content = ""

        for path in ["CONTRIBUTING.md", "contributing.md", ".github/CONTRIBUTING.md", "docs/CONTRIBUTING.md"]:
            try:
                content_file = repo.get_contents(path)
                has_contributing = True
                if hasattr(content_file, "decoded_content"):
                    contributing_content = content_file.decoded_content.decode("utf-8", errors="replace")[:2000]
                break
            except GithubException:
                continue

        has_pr_template = False
        for path in [".github/PULL_REQUEST_TEMPLATE.md", ".github/pull_request_template.md",
                      "PULL_REQUEST_TEMPLATE.md", ".github/PULL_REQUEST_TEMPLATE/default.md"]:
            try:
                repo.get_contents(path)
                has_pr_template = True
                break
            except GithubException:
                continue

        if has_contributing:
            lower_content = contributing_content.lower()
            if "do not submit" in lower_content or "no unsolicited" in lower_content:
                notes.append("CONTRIBUTING.md may discourage unsolicited PRs — review before submitting")
            if "cla" in lower_content or "contributor license" in lower_content:
                notes.append("Repository requires a Contributor License Agreement (CLA)")
            if "issue first" in lower_content or "open an issue" in lower_content:
                notes.append("CONTRIBUTING.md requests opening an issue before submitting a PR")

        return {
            "has_contributing": has_contributing,
            "has_pr_template": has_pr_template,
            "notes": notes,
        }

    def run_pr_preflight(
        self,
        repo_full_name: str,
        branch_name: str,
        issue_number: Optional[int] = None,
    ) -> dict:
        """
        Combined pre-flight check: duplicates, assignees, and contribution policy.
        Returns {"ok": bool, "blockers": [str], "warnings": [str], "details": {...}}
        """
        blockers: List[str] = []
        warnings: List[str] = []

        dup_check = self.check_existing_prs(repo_full_name, branch_name, issue_number)
        if dup_check["has_duplicate"]:
            for msg in dup_check["issues"]:
                if "closed without merge" in msg:
                    warnings.append(msg)
                else:
                    blockers.append(msg)

        assignee_check = {}
        if issue_number:
            assignee_check = self.check_issue_assignee(repo_full_name, issue_number)
            if assignee_check.get("assigned"):
                names = ", ".join(assignee_check["assignees"])
                warnings.append(f"Issue #{issue_number} is already assigned to: {names}")

        policy_check = self.check_contribution_policy(repo_full_name)
        for note in policy_check.get("notes", []):
            warnings.append(note)

        return {
            "ok": len(blockers) == 0,
            "blockers": blockers,
            "warnings": warnings,
            "details": {
                "duplicate_check": dup_check,
                "assignee_check": assignee_check,
                "policy_check": policy_check,
            },
        }

    def get_pull_request_checks(self, repo_full_name: str, pr_number: int) -> dict:
        """Return normalized check-run status for the latest commit on a pull request."""
        repo = self.client.get_repo(repo_full_name)
        pull_request = repo.get_pull(pr_number)
        commit = repo.get_commit(pull_request.head.sha)
        combined_status = commit.get_combined_status()
        checks = []

        for check in commit.get_check_runs():
            checks.append({
                "name": check.name,
                "status": check.status,
                "conclusion": check.conclusion,
                "details_url": check.details_url,
            })

        failed = [
            check for check in checks
            if check["conclusion"] in {"failure", "cancelled", "timed_out", "action_required"}
        ]
        return {
            "repository": repo_full_name,
            "pull_request_number": pr_number,
            "commit_sha": pull_request.head.sha,
            "state": combined_status.state,
            "total_checks": len(checks),
            "passed_checks": sum(1 for check in checks if check["conclusion"] == "success"),
            "failed_checks": len(failed),
            "checks": checks,
            "ready_for_review": bool(checks) and not failed and all(
                check["status"] == "completed" for check in checks
            ),
        }

        def get_pull_request_failure_logs(self, repo_full_name: str, pr_number: int) -> dict:
            """Fetch bounded GitHub Actions logs for failed checks on a pull request."""
            repo = self.client.get_repo(repo_full_name)
            pull_request = repo.get_pull(pr_number)
            runs = repo.get_workflow_runs(head_sha=pull_request.head.sha)
            failures: list[dict[str, str]] = []
            for workflow_run in runs:
                if workflow_run.conclusion not in {"failure", "timed_out", "cancelled", "action_required"}:
                    continue
                try:
                    raw_logs = workflow_run.get_logs()
                    if isinstance(raw_logs, bytes):
                        logs = raw_logs.decode("utf-8", errors="replace")
                    else:
                        logs = str(raw_logs)
                except Exception as error:
                    logs = f"Unable to download workflow logs: {error}"
                failures.append({
                    "name": workflow_run.name,
                    "status": workflow_run.status,
                    "conclusion": workflow_run.conclusion,
                    "url": workflow_run.html_url,
                    "logs": logs[-100_000:],
                })
            return {
                "repository": repo_full_name,
                "pull_request_number": pr_number,
                "commit_sha": pull_request.head.sha,
                "failures": failures,
            }

        def apply_pull_request_followup(
            self,
            repo_full_name: str,
            pr_number: int,
            file_rewrites: dict[str, str],
            commit_message: str,
        ) -> dict:
            """Commit approved follow-up rewrites to the existing PR head branch."""
            upstream = self.client.get_repo(repo_full_name)
            pull_request = upstream.get_pull(pr_number)
            if pull_request.head.repo is None:
                raise RuntimeError("Pull request head repository is unavailable")
            fork = self.client.get_repo(pull_request.head.repo.full_name)
            updated: list[str] = []
            for path, content in file_rewrites.items():
                current = fork.get_contents(path, ref=pull_request.head.ref)
                if isinstance(current, list):
                    raise ValueError(f"Follow-up path is a directory: {path}")
                fork.update_file(
                    path,
                    commit_message,
                    content,
                    current.sha,
                    branch=pull_request.head.ref,
                )
                updated.append(path)
            return {
                "repository": repo_full_name,
                "pull_request_number": pr_number,
                "branch": pull_request.head.ref,
                "files": updated,
            }
