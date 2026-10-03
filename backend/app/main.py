import os
import json
import asyncio
import hashlib
import hmac
import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from datetime import datetime

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from fastapi import FastAPI, Depends, Query, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, engine, Base
from app.models import (
    Repository as RepoModel,
    Issue as IssueModel,
    Run as RunModel,
    PullRequest as PRModel,
    FeatureSuggestion as FeatureModel,
    AgentEvent,
    RepositoryMemory,
    AgentRun,
    AgentApproval,
    AgentReviewFinding,
    AgentMemoryFact,
)
from app.scheduler import get_scheduler
from app.schemas import *
from app.agent_routes import router as agent_router
from app.pr_routes import router as pr_router
from app.sandbox_routes import router as sandbox_router
from app.feature_routes import router as feature_router


logger = logging.getLogger("uvicorn.error")
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Mark any runs left in "running" state from a previous crashed session as failed
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        stale = await session.execute(select(RunModel).where(RunModel.status == "running"))
        for run in stale.scalars().all():
            run.status = "failed"
            run.summary = "Server restarted while run was active"
            run.completed_at = datetime.utcnow()
        await session.commit()

        stale_agents = await session.execute(
            select(AgentRun).where(
                AgentRun.status.in_(["planning", "executing", "verifying", "reviewing"])
            )
        )
        for agent_run in stale_agents.scalars().all():
            agent_run.status = "failed"
            agent_run.failure_reason = "Server restarted while agent workflow was active"
        await session.commit()

    scheduler = get_scheduler()
    scheduler.start()

    yield

    scheduler.stop()


app = FastAPI(title="Patchwork API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count"],
)
app.include_router(agent_router)
app.include_router(pr_router)
app.include_router(sandbox_router)
app.include_router(feature_router)


@app.middleware("http")
async def log_api_requests(request: Request, call_next):
    if not request.url.path.startswith("/api/"):
        return await call_next(request)

    started_at = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = (time.perf_counter() - started_at) * 1000
        logger.exception(
            "API request failed method=%s path=%s duration_ms=%.1f",
            request.method,
            request.url.path,
            duration_ms,
        )
        raise

    duration_ms = (time.perf_counter() - started_at) * 1000
    logger.info(
        "API request method=%s path=%s status=%d duration_ms=%.1f",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


@app.get("/api/telemetry")
async def get_telemetry(session: AsyncSession = Depends(get_db)):
    try:
        from sqlalchemy import select, func
        from app.models import Issue, PullRequest, FeatureSuggestion
        import json

        total_issues = (await session.execute(select(func.count(Issue.id)))).scalar() or 0
        suitable_issues = (await session.execute(select(func.count(Issue.id)).where(Issue.is_suitable == True))).scalar() or 0
        issue_precision = round((suitable_issues / total_issues * 100) if total_issues else 0, 1)

        features = (await session.execute(select(FeatureSuggestion.sandbox_result).where(FeatureSuggestion.sandbox_result.isnot(None)))).scalars().all()
        issues = (await session.execute(select(Issue.sandbox_result).where(Issue.sandbox_result.isnot(None)))).scalars().all()

        all_results = []
        for r in features + issues:
            try:
                if r:
                    all_results.append(json.loads(r))
            except (TypeError, json.JSONDecodeError):
                pass

        first_pass_count = 0
        repair_attempts = 0
        repair_successes = 0

        for res in all_results:
            attempts = res.get("attempts_used", 1)
            checks = res.get("checks", {})
            tests_ok = checks.get("tests", {}).get("passed", False) and checks.get("syntax", {}).get("passed", False)

            if attempts == 1 and tests_ok:
                first_pass_count += 1
            if attempts > 1:
                repair_attempts += 1
                if res.get("healed") or tests_ok:
                    repair_successes += 1

        total_sandboxed = len(all_results)
        first_pass_rate = round((first_pass_count / total_sandboxed * 100) if total_sandboxed else 0, 1)
        repair_success_rate = round((repair_successes / repair_attempts * 100) if repair_attempts else 0, 1)

        prs = (await session.execute(select(PullRequest.status, PullRequest.error_message))).all()
        merged = sum(1 for pr in prs if pr.status == "merged")
        closed = sum(1 for pr in prs if pr.status == "closed")
        total_prs = len(prs)

        resolved_prs = merged + closed
        merge_rate = round((merged / resolved_prs * 100) if resolved_prs else 0, 1)
        duplicate_blocks = sum(1 for pr in prs if pr.status == "failed" and pr.error_message and ("duplicate" in pr.error_message.lower() or "policy" in pr.error_message.lower()))
        duplicate_pr_rate = round((duplicate_blocks / total_prs * 100) if total_prs else 0, 1)

        return {
            "metrics": {
                "issue_selection_precision": f"{issue_precision}%",
                "first_pass_test_success": f"{first_pass_rate}%",
                "repair_success_rate": f"{repair_success_rate}%",
                "merge_rate": f"{merge_rate}%",
                "duplicate_pr_rate": f"{duplicate_pr_rate}%",
                "cost_per_contribution": "~$0.02 compute",
                "time_per_contribution": "~45 seconds"
            }
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    from app.llm_client import get_llm_client
    from app.model_router import model_for, provider_name

    provider = provider_name()
    configured_model = model_for("coding")
    try:
        response = await get_llm_client().list()
        model_available = any(
            model.model == configured_model for model in response.models
        )
        provider_connected = True
    except Exception:
        model_available = False
        provider_connected = False

    return HealthResponse(
        status="ok",
        ollama_connected=provider_connected,
        configured_model=configured_model,
        model_available=model_available,
        provider=provider,
    )


@app.post("/api/webhooks/github")
async def github_webhook(request: Request, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """Accept signed GitHub events for future issue, review, and CI automations."""
    if not GITHUB_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="GITHUB_WEBHOOK_SECRET is not configured")

    body = await request.body()
    signature = request.headers.get("x-hub-signature-256", "")
    expected = "sha256=" + hmac.new(
        GITHUB_WEBHOOK_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload = json.loads(body)
    event_name = request.headers.get("x-github-event", "unknown")
    repository = payload.get("repository", {}).get("full_name")
    db.add(AgentEvent(
        repository=repository,
        event_type=f"github_webhook:{event_name}",
        payload=json.dumps({
            "action": payload.get("action"),
            "sender": payload.get("sender", {}).get("login"),
            "repository": repository,
        }),
    ))
    await db.commit()
    return {"status": "accepted", "event": event_name}


@app.get("/api/repositories", response_model=list[RepositoryResponse])
async def list_repositories(
    language: Optional[str] = Query("Python"),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
) -> list[RepositoryResponse]:
    query = select(RepoModel).where(RepoModel.is_active == True)

    if language:
        query = query.where(RepoModel.language == language)

    query = query.order_by(desc(RepoModel.fit_score)).limit(limit)

    result = await db.execute(query)
    repos = result.scalars().all()

    return [
        RepositoryResponse(
            full_name=repo.full_name,
            owner=repo.owner,
            name=repo.name,
            description=repo.description or "",
            language=repo.language or "Unknown",
            stars=repo.stars,
            open_issues=repo.open_issues,
            fit_score=repo.fit_score,
            trend_percent=repo.trend_percent,
            url=repo.url
        )
        for repo in repos
    ]


@app.get("/api/repositories/{repo_full_name:path}/intelligence", response_model=RepositoryIntelligenceResponse)
async def repository_intelligence(repo_full_name: str) -> RepositoryIntelligenceResponse:
    """Build an AST-backed repository briefing for agent context and review."""
    from app.intelligence_service import build_repository_graph

    try:
        graph = await build_repository_graph(repo_full_name)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Repository analysis failed: {exc}") from exc
    return RepositoryIntelligenceResponse(repository=repo_full_name, **graph)


@app.get("/api/issues", response_model=list[CandidateIssueResponse])
async def list_issues(
    repository: Optional[str] = Query(None),
    difficulty: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    response: Response = None,
    db: AsyncSession = Depends(get_db),
) -> list[CandidateIssueResponse]:
    query = select(IssueModel).where(IssueModel.is_suitable == True)

    if repository:
        query = query.where(IssueModel.repository == repository)

    if difficulty:
        query = query.where(IssueModel.difficulty == difficulty)

    total_query = select(func.count(IssueModel.id)).where(IssueModel.is_suitable == True)
    if repository:
        total_query = total_query.where(IssueModel.repository == repository)
    if difficulty:
        total_query = total_query.where(IssueModel.difficulty == difficulty)
    total = await db.scalar(total_query) or 0
    if response is not None:
        response.headers["X-Total-Count"] = str(total)

    query = query.order_by(desc(IssueModel.suitability_score)).offset(offset).limit(limit)

    result = await db.execute(query)
    issues = result.scalars().all()
    from app.contribution_service import rank_issue_candidates

    ranked = rank_issue_candidates(
        [
            {
                "id": issue.id,
                "repository": issue.repository,
                "title": issue.title,
                "number": issue.number,
                "label": issue.label,
                "difficulty": issue.difficulty,
                "url": issue.url,
                "body": issue.body,
                "suitability_score": issue.suitability_score,
                "is_suitable": issue.is_suitable,
                "ai_analysis": issue.ai_analysis,
                "agent_status": issue.agent_status,
                "updated_at": issue.updated_at.isoformat() if issue.updated_at else "",
            }
            for issue in issues
        ],
        limit=limit,
    )
    issues_by_id = {issue.id: issue for issue in issues}

    return [
        CandidateIssueResponse(
            id=item["id"],
            repository=item["repository"],
            title=item["title"],
            number=item["number"],
            label=item["label"] or "unlabeled",
            difficulty=item["difficulty"],
            url=item["url"],
            body=item["body"],
            suitability_score=item["suitability_score"],
            updated_at=_format_time_ago(issues_by_id[item["id"]].updated_at),
            ai_analysis=item["ai_analysis"],
            agent_status=item["agent_status"],
            sandbox_result=(
                json.loads(issues_by_id[item["id"]].sandbox_result)
                if issues_by_id[item["id"]].sandbox_result
                else None
            ),
            selection_score=item["selection_score"],
            selection_reasons=item["selection_reasons"],
        )
        for item in ranked
    ]


@app.get("/api/issues/{issue_id}/acceptance-score", response_model=AcceptanceScoreResponse)
async def issue_acceptance_score(
    issue_id: int,
    db: AsyncSession = Depends(get_db),
) -> AcceptanceScoreResponse:
    """Estimate whether a maintainer is likely to welcome work on an issue."""
    issue = await db.get(IssueModel, issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    from app.contribution_service import score_issue_acceptance
    from app.github_service import GitHubService

    try:
        preflight = await asyncio.to_thread(
            GitHubService().run_pr_preflight,
            issue.repository,
            f"patchwork/fix-issue-{issue.number}",
            issue.number,
        )
        result = score_issue_acceptance(
            {
                "difficulty": issue.difficulty,
                "label": issue.label,
                "body": issue.body,
            },
            preflight,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Acceptance scoring failed: {exc}") from exc

    return AcceptanceScoreResponse(
        issue_id=issue.id,
        repository=issue.repository,
        issue_number=issue.number,
        **result,
    )


@app.get("/api/runs", response_model=list[RunResponse])
async def list_runs(
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db)
) -> list[RunResponse]:
    query = select(RunModel).order_by(desc(RunModel.created_at)).limit(limit)

    result = await db.execute(query)
    runs = result.scalars().all()

    return [
        RunResponse(
            id=run.id,
            name=run.name,
            status=run.status,
            summary=run.summary,
            repositories_scanned=run.repositories_scanned,
            issues_found=run.issues_found,
            created_at=_format_datetime(run.created_at)
        )
        for run in runs
    ]


@app.post("/api/discovery/trigger", response_model=DiscoveryTriggerResponse)
async def trigger_discovery() -> DiscoveryTriggerResponse:
    scheduler = get_scheduler()
    try:
        run_id = await scheduler.run_discovery_now()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return DiscoveryTriggerResponse(
        message="Discovery started",
        run_id=run_id
    )


@app.post("/api/issues/{issue_id}/analyze", response_model=AnalyzeIssueResponse)
async def analyze_issue(
    issue_id: int,
    db: AsyncSession = Depends(get_db),
) -> AnalyzeIssueResponse:
    """Clone the repo, run Ollama analysis, return the proposed patch for review."""
    issue = await db.get(IssueModel, issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    issue.agent_status = "analyzing"
    db.add(AgentEvent(
        issue_id=issue.id,
        repository=issue.repository,
        event_type="issue_analysis_started",
        payload=json.dumps({"issue_number": issue.number}),
    ))
    await db.commit()

    from app.agent_service import analyze_issue as _analyze

    logger.info(
        "Issue analysis request accepted issue_id=%s repo=%s issue_number=%s",
        issue.id,
        issue.repository,
        issue.number,
    )
    try:
        result = await _analyze(
            repo_full_name=issue.repository,
            issue_number=issue.number,
            issue_title=issue.title,
            issue_body=issue.body or "",
        )
    except Exception as e:
        logger.exception(
            "Issue analysis request failed issue_id=%s repo=%s issue_number=%s",
            issue.id,
            issue.repository,
            issue.number,
        )
        issue.agent_status = "analysis_failed"
        issue.ai_analysis = f"Analysis failed: {e}"
        await db.commit()
        raise HTTPException(status_code=500, detail=str(e))

    issue.ai_analysis = result["analysis"]
    issue.agent_status = "analyzed"
    db.add(AgentEvent(
        issue_id=issue.id,
        repository=issue.repository,
        event_type="issue_analysis_completed",
        payload=json.dumps({"files": result["relevant_files"]}),
    ))
    await db.commit()
    logger.info(
        "Issue analysis request completed issue_id=%s repo=%s issue_number=%s rewritten_files=%d",
        issue.id,
        issue.repository,
        issue.number,
        len(result["file_rewrites"]),
    )

    return AnalyzeIssueResponse(
        issue_id=issue_id,
        analysis=result["analysis"],
        pr_title=result["pr_title"],
        pr_body=result["pr_body"],
        relevant_files=result["relevant_files"],
        file_rewrites=result["file_rewrites"],
    )



@app.post("/api/issues/{issue_id}/review-patch", response_model=DiffReviewResponse)
async def api_review_patch(
    issue_id: int, 
    body: DiffReviewRequest,
    session: AsyncSession = Depends(get_db)
):
    issue = await session.get(IssueModel, issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    from app.agent_service import review_patch
    review_data = await review_patch(
        repo_full_name=issue.repository,
        issue_title=issue.title,
        issue_body=issue.body,
        acceptance_criteria=body.acceptance_criteria,
        file_rewrites=body.file_rewrites,
        sandbox_result=body.sandbox_result,
    )
    
    return review_data


@app.post("/api/issues/{issue_id}/regression-test", response_model=RegressionTestResponse)
async def generate_issue_regression_test(
    issue_id: int,
    db: AsyncSession = Depends(get_db),
) -> RegressionTestResponse:
    """Generate and run a focused regression test against the unmodified repository."""
    issue = await db.get(IssueModel, issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    from app.agent_service import generate_regression_test
    from app.sandbox_service import run_sandbox_validation

    try:
        generated = await generate_regression_test(
            repo_full_name=issue.repository,
            issue_number=issue.number,
            issue_title=issue.title,
            issue_body=issue.body or "",
        )
        before_result = await run_sandbox_validation(
            repo_full_name=issue.repository,
            file_rewrites={generated["test_path"]: generated["test_content"]},
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Regression test generation failed: {exc}") from exc

    return RegressionTestResponse(
        issue_id=issue_id,
        test_path=generated["test_path"],
        test_content=generated["test_content"],
        explanation=generated["explanation"],
        before_result=SandboxVerifyResponse(**before_result),
        fails_before_patch=(
            not before_result["success"]
            and before_result["checks"]["tests"]["failed_count"] > 0
        ),
    )


@app.get("/api/issues/{issue_id}/trajectory", response_model=list[AgentEventResponse])
async def issue_trajectory(
    issue_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[AgentEventResponse]:
    """Return persisted agent events for a contribution attempt."""
    result = await db.execute(
        select(AgentEvent)
        .where(AgentEvent.issue_id == issue_id)
        .order_by(AgentEvent.created_at)
    )
    events = result.scalars().all()
    return [
        AgentEventResponse(
            id=event.id,
            event_type=event.event_type,
            payload=json.loads(event.payload) if event.payload else {},
            created_at=_format_datetime(event.created_at),
        )
        for event in events
    ]


@app.get("/api/repositories/{repo_full_name:path}/memory", response_model=RepositoryMemoryResponse)
async def get_repository_memory(
    repo_full_name: str,
    db: AsyncSession = Depends(get_db),
) -> RepositoryMemoryResponse:
    record = (
        await db.execute(
            select(RepositoryMemory).where(RepositoryMemory.repository == repo_full_name)
        )
    ).scalar_one_or_none()
    return RepositoryMemoryResponse(
        repository=repo_full_name,
        memory=record.memory if record else "",
        updated_at=_format_datetime(record.updated_at) if record else "never",
    )


@app.put("/api/repositories/{repo_full_name:path}/memory", response_model=RepositoryMemoryResponse)
async def update_repository_memory(
    repo_full_name: str,
    body: RepositoryMemoryRequest,
    db: AsyncSession = Depends(get_db),
) -> RepositoryMemoryResponse:
    record = (
        await db.execute(
            select(RepositoryMemory).where(RepositoryMemory.repository == repo_full_name)
        )
    ).scalar_one_or_none()
    if record:
        record.memory = body.memory
    else:
        record = RepositoryMemory(repository=repo_full_name, memory=body.memory)
        db.add(record)
    await db.commit()
    await db.refresh(record)
    return RepositoryMemoryResponse(
        repository=repo_full_name,
        memory=record.memory,
        updated_at=_format_datetime(record.updated_at),
    )

@app.post("/api/issues/{issue_id}/create-pr", response_model=PullRequestResponse)
async def create_pr_for_issue(
    issue_id: int,
    body: CreatePRRequest,
    db: AsyncSession = Depends(get_db),
) -> PullRequestResponse:
    """Apply the approved patch and open a PR on GitHub."""
    issue = await db.get(IssueModel, issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    if not body.file_rewrites:
        raise HTTPException(status_code=400, detail="No file rewrites provided")

    sandbox_result = json.loads(issue.sandbox_result) if issue.sandbox_result else None
    if not sandbox_result or sandbox_result.get("overall_status") != "passed":
        raise HTTPException(
            status_code=409,
            detail="A fully passing sandbox verification is required before creating a pull request",
        )

    # Create a pending PR record
    pr_record = PRModel(
        repository=issue.repository,
        title=body.pr_title,
        status="creating",
        issue_number=issue.number,
        issue_url=issue.url,
        patch_content="\n\n".join(
            f"### {p}\n{c}" for p, c in body.file_rewrites.items()
        ),
        ai_summary=issue.ai_analysis,
        pr_body=body.pr_body,
        sandbox_result=issue.sandbox_result,
    )
    db.add(pr_record)
    issue.agent_status = "creating_pr"
    await db.commit()
    await db.refresh(pr_record)
    pr_id = pr_record.id

    from app.agent_service import create_pull_request as _create_pr

    try:
        pr_timeout = float(os.getenv("PR_CREATION_TIMEOUT_SECONDS", "180"))
        result = await asyncio.wait_for(
            _create_pr(
                repo_full_name=issue.repository,
                issue_number=issue.number,
                pr_title=body.pr_title,
                pr_body=body.pr_body,
                file_rewrites=body.file_rewrites,
            ),
            timeout=pr_timeout,
        )
        pr_record.status = "open"
        pr_record.url = result["pr_url"]
        pr_record.number = result["pr_number"]
        pr_record.branch_name = result["branch"]
        issue.agent_status = "pr_created"
    except asyncio.TimeoutError as e:
        pr_record.status = "failed"
        pr_record.error_message = f"PR creation timed out after {pr_timeout:.0f} seconds"
        issue.agent_status = "pr_failed"
        await db.commit()
        raise HTTPException(status_code=504, detail=pr_record.error_message) from e
    except Exception as e:
        pr_record.status = "failed"
        pr_record.error_message = str(e)
        issue.agent_status = "pr_failed"
        await db.commit()
        raise HTTPException(status_code=500, detail=str(e))

    await db.commit()
    await db.refresh(pr_record)

    return PullRequestResponse(
        id=pr_record.id,
        repository=pr_record.repository,
        title=pr_record.title,
        number=pr_record.number,
        url=pr_record.url,
        status=pr_record.status,
        issue_number=pr_record.issue_number,
        issue_url=pr_record.issue_url,
        ai_summary=pr_record.ai_summary,
        created_at=_format_datetime(pr_record.created_at),
    )


def _format_time_ago(dt) -> str:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    dt_utc = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt

    delta = now - dt_utc

    days = delta.days
    hours = delta.seconds // 3600
    minutes = (delta.seconds % 3600) // 60

    if days > 0:
        return f"{days} day{'s' if days > 1 else ''} ago"
    elif hours > 0:
        return f"{hours} hour{'s' if hours > 1 else ''} ago"
    elif minutes > 0:
        return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
    else:
        return "just now"


def _format_datetime(dt) -> str:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    dt_utc = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt

    delta = now - dt_utc

    if delta.days == 0:
        return f"Today, {dt_utc.strftime('%H:%M')}"
    elif delta.days == 1:
        return f"Yesterday, {dt_utc.strftime('%H:%M')}"
    else:
        return dt_utc.strftime("%B %d, %H:%M")