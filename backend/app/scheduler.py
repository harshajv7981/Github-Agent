import asyncio
from datetime import datetime
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import Repository as RepoModel, Issue as IssueModel, Run as RunModel
from app.github_service import GitHubService


class DiscoveryScheduler:
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.github_service = GitHubService()

    def start(self):
        """Start the scheduler with daily discovery at 9 AM IST (3:30 AM UTC)."""
        self.scheduler.add_job(
            self.run_daily_discovery,
            CronTrigger(hour=3, minute=30, timezone='UTC'),
            id='daily_discovery',
            name='Daily Repository Discovery',
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        self.scheduler.start()

    def stop(self):
        """Stop the scheduler."""
        self.scheduler.shutdown()

    async def run_daily_discovery(self):
        """Run the full discovery workflow: fetch repos, find issues, store in DB."""
        async with AsyncSessionLocal() as session:
            run = RunModel(
                name="Daily repository discovery",
                status="running",
                started_at=datetime.utcnow()
            )
            session.add(run)
            await session.commit()

            try:
                trending_repos = await self.github_service.discover_trending_repositories(
                    language="python",
                    max_results=25
                )

                popular_repos = await self.github_service.discover_popular_repositories(
                    language="python",
                    max_results=25
                )

                all_repos = trending_repos + popular_repos

                if not all_repos:
                    raise Exception("No repositories found from GitHub API")

                repos_scanned = 0
                total_issues = 0
                failed_repos = 0

                for repo_data in all_repos[:50]:
                    try:
                        existing_repo = await session.execute(
                            select(RepoModel).where(
                                RepoModel.full_name == repo_data["full_name"]
                            )
                        )
                        existing_repo = existing_repo.scalar_one_or_none()

                        if existing_repo:
                            for key, value in repo_data.items():
                                setattr(existing_repo, key, value)
                            repo_record = existing_repo
                        else:
                            repo_record = RepoModel(**repo_data)
                            session.add(repo_record)

                        await session.commit()
                        repos_scanned += 1
                        run.repositories_scanned = repos_scanned
                        run.issues_found = total_issues
                        await session.commit()

                        issues = await self.github_service.find_suitable_issues(
                            repo_data["full_name"]
                        )

                        for issue_data in issues:
                            try:
                                existing_issue = await session.execute(
                                    select(IssueModel).where(
                                        IssueModel.repository == issue_data["repository"],
                                        IssueModel.number == issue_data["number"]
                                    )
                                )
                                existing_issue = existing_issue.scalar_one_or_none()

                                if existing_issue:
                                    for key, value in issue_data.items():
                                        setattr(existing_issue, key, value)
                                else:
                                    issue_record = IssueModel(**issue_data)
                                    session.add(issue_record)
                                    total_issues += 1

                                run.issues_found = total_issues
                                await session.commit()
                            except Exception as issue_error:
                                print(f"Error saving issue {issue_data.get('number', 'unknown')}: {issue_error}")
                                await session.rollback()
                                continue

                        await asyncio.sleep(0.5)

                    except Exception as repo_error:
                        failed_repos += 1
                        print(f"Error processing repo {repo_data.get('full_name', 'unknown')}: {repo_error}")
                        await session.rollback()
                        continue

                run.status = "needs_review" if failed_repos else "completed"
                run.repositories_scanned = repos_scanned
                run.issues_found = total_issues
                run.summary = (
                    f"{repos_scanned} repositories scanned; {total_issues} issues found"
                    + (f"; {failed_repos} repositories failed" if failed_repos else "")
                )
                run.completed_at = datetime.utcnow()
                await session.commit()

            except Exception as e:
                print(f"Discovery error: {e}")
                import traceback
                traceback.print_exc()
                run.status = "failed"
                run.summary = f"Discovery failed: {str(e)}"
                run.completed_at = datetime.utcnow()
                await session.commit()

    async def run_discovery_now(self) -> int:
        """Trigger discovery immediately and return the run ID."""
        async with AsyncSessionLocal() as session:
            running = await session.execute(
                select(RunModel.id).where(RunModel.status == "running").limit(1)
            )
            if running.scalar_one_or_none() is not None:
                raise RuntimeError("A discovery run is already in progress")

            run = RunModel(
                name="Manual repository discovery",
                status="running",
                started_at=datetime.utcnow()
            )
            session.add(run)
            await session.commit()
            await session.refresh(run)
            run_id = run.id

        asyncio.create_task(self._execute_discovery(run_id))
        return run_id

    async def _execute_discovery(self, run_id: int):
        """Execute discovery in background."""
        async with AsyncSessionLocal() as session:
            run = await session.get(RunModel, run_id)

            try:
                trending_repos = await self.github_service.discover_trending_repositories(
                    language="python",
                    max_results=25
                )

                popular_repos = await self.github_service.discover_popular_repositories(
                    language="python",
                    max_results=25
                )

                all_repos = trending_repos + popular_repos

                if not all_repos:
                    raise Exception("No repositories found from GitHub API")

                repos_scanned = 0
                total_issues = 0
                failed_repos = 0

                for repo_data in all_repos[:50]:
                    try:
                        existing_repo = await session.execute(
                            select(RepoModel).where(
                                RepoModel.full_name == repo_data["full_name"]
                            )
                        )
                        existing_repo = existing_repo.scalar_one_or_none()

                        if existing_repo:
                            for key, value in repo_data.items():
                                setattr(existing_repo, key, value)
                        else:
                            repo_record = RepoModel(**repo_data)
                            session.add(repo_record)

                        await session.commit()
                        repos_scanned += 1
                        run.repositories_scanned = repos_scanned
                        run.issues_found = total_issues
                        await session.commit()

                        issues = await self.github_service.find_suitable_issues(
                            repo_data["full_name"]
                        )

                        for issue_data in issues:
                            try:
                                existing_issue = await session.execute(
                                    select(IssueModel).where(
                                        IssueModel.repository == issue_data["repository"],
                                        IssueModel.number == issue_data["number"]
                                    )
                                )
                                existing_issue = existing_issue.scalar_one_or_none()

                                if existing_issue:
                                    for key, value in issue_data.items():
                                        setattr(existing_issue, key, value)
                                else:
                                    issue_record = IssueModel(**issue_data)
                                    session.add(issue_record)
                                    total_issues += 1

                                run.issues_found = total_issues
                                await session.commit()
                            except Exception as issue_error:
                                print(f"Error saving issue {issue_data.get('number', 'unknown')}: {issue_error}")
                                await session.rollback()
                                continue

                        await asyncio.sleep(0.5)

                    except Exception as repo_error:
                        failed_repos += 1
                        print(f"Error processing repo {repo_data.get('full_name', 'unknown')}: {repo_error}")
                        await session.rollback()
                        continue

                run.status = "needs_review" if failed_repos else "completed"
                run.repositories_scanned = repos_scanned
                run.issues_found = total_issues
                run.summary = (
                    f"{repos_scanned} repositories scanned; {total_issues} issues found"
                    + (f"; {failed_repos} repositories failed" if failed_repos else "")
                )
                run.completed_at = datetime.utcnow()
                await session.commit()

            except Exception as e:
                print(f"Discovery error: {e}")
                import traceback
                traceback.print_exc()
                run.status = "failed"
                run.summary = f"Discovery failed: {str(e)}"
                run.completed_at = datetime.utcnow()
                await session.commit()


scheduler_instance: Optional[DiscoveryScheduler] = None


def get_scheduler() -> DiscoveryScheduler:
    global scheduler_instance
    if scheduler_instance is None:
        scheduler_instance = DiscoveryScheduler()
    return scheduler_instance
