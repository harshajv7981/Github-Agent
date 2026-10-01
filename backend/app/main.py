import os
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, Optional
from datetime import datetime

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from fastapi import FastAPI, Depends, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from ollama import AsyncClient
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, engine, Base
from app.models import (
    Repository as RepoModel,
    Issue as IssueModel,
    Run as RunModel,
    PullRequest as PRModel,
    FeatureSuggestion as FeatureModel,
)
from app.scheduler import get_scheduler


OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:9b")


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
)


class RepositoryResponse(BaseModel):
    full_name: str
    owner: str
    name: str
    description: str
    language: str
    stars: int
    open_issues: int
    fit_score: int
    trend_percent: int
    url: str


class CandidateIssueResponse(BaseModel):
    id: int
    repository: str
    title: str
    number: int
    label: str
    difficulty: Literal["good_first_issue", "intermediate"]
    url: str
    body: Optional[str]
    suitability_score: int
    updated_at: str
    ai_analysis: Optional[str] = None
    agent_status: Optional[str] = None
    sandbox_result: Optional[dict] = None


class RunResponse(BaseModel):
    id: int
    name: str
    status: Literal["running", "completed", "failed", "needs_review"]
    summary: Optional[str]
    repositories_scanned: int
    issues_found: int
    created_at: str


class HealthResponse(BaseModel):
    status: Literal["ok"]
    ollama_connected: bool
    configured_model: str
    model_available: bool


class DiscoveryTriggerResponse(BaseModel):
    message: str
    run_id: int



class DiffReviewFinding(BaseModel):
    severity: str
    file_path: str
    explanation: str
    suggested_fix: Optional[str] = None

class DiffReviewResponse(BaseModel):
    decision: str
    summary: str
    findings: list[DiffReviewFinding]
    
class DiffReviewRequest(BaseModel):
    file_rewrites: dict[str, str]
    acceptance_criteria: list[str] = []
    sandbox_result: Optional[dict] = None

class AnalyzeIssueResponse(BaseModel):
    issue_id: int
    analysis: str
    pr_title: str
    pr_body: str
    relevant_files: list[str]
    file_rewrites: dict[str, str]
    acceptance_criteria: list[str] = []
    is_actionable: bool = True


class PullRequestResponse(BaseModel):
    id: int
    repository: str
    title: str
    number: Optional[int]
    url: Optional[str]
    status: str
    issue_number: Optional[int]
    issue_url: Optional[str]
    ai_summary: Optional[str]
    sandbox_result: Optional[dict] = None
    created_at: str


class CreatePRRequest(BaseModel):
    pr_title: str
    pr_body: str
    file_rewrites: dict[str, str]


class FeatureSuggestionResponse(BaseModel):
    id: int
    repository: str
    title: str
    description: str
    category: str
    complexity: str
    impact_score: int
    implementation_plan: str
    suggested_files: list[str]
    status: str
    ai_analysis: Optional[str] = None
    pr_title: Optional[str] = None
    pr_body: Optional[str] = None
    sandbox_result: Optional[dict] = None
    contribution_source: str = "ai_proposed"
    review_required: bool = True
    created_at: str


class ImplementFeatureResponse(BaseModel):
    feature_id: int
    analysis: str
    pr_title: str
    pr_body: str
    relevant_files: list[str]
    file_rewrites: dict[str, str]


class SandboxVerifyRequest(BaseModel):
    repo_full_name: str
    file_rewrites: dict[str, str]


class SandboxVerifyResponse(BaseModel):
    success: bool
    overall_status: str
    score: int
    execution_time_seconds: float
    environment: str
    checks: dict
    summary: str
    modified_files: list[str]


class AutoHealRequest(BaseModel):
    repo_full_name: str
    title: str
    file_rewrites: dict[str, str]
    sandbox_diagnostics: dict


class AutoHealResponse(BaseModel):
    file_rewrites: dict[str, str]
    healing_analysis: str
    healed: bool
    attempts_used: Optional[int] = None
    diff_history: Optional[list[dict]] = None
    sandbox_result: Optional[dict] = None


class SuggestFeaturesResponse(BaseModel):
    repository: str
    count: int
    suggestions: list[FeatureSuggestionResponse]



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
    try:
        response = await AsyncClient(host=OLLAMA_HOST).list()
        model_available = any(
            model.model == OLLAMA_MODEL for model in response.models
        )
        ollama_connected = True
    except Exception:
        model_available = False
        ollama_connected = False

    return HealthResponse(
        status="ok",
        ollama_connected=ollama_connected,
        configured_model=OLLAMA_MODEL,
        model_available=model_available,
    )


@app.get("/api/repositories", response_model=list[RepositoryResponse])
async def list_repositories(
    language: Optional[str] = Query(None),
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


@app.get("/api/issues", response_model=list[CandidateIssueResponse])
async def list_issues(
    repository: Optional[str] = Query(None),
    difficulty: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
) -> list[CandidateIssueResponse]:
    query = select(IssueModel).where(IssueModel.is_suitable == True)

    if repository:
        query = query.where(IssueModel.repository == repository)

    if difficulty:
        query = query.where(IssueModel.difficulty == difficulty)

    query = query.order_by(desc(IssueModel.suitability_score)).limit(limit)

    result = await db.execute(query)
    issues = result.scalars().all()

    return [
        CandidateIssueResponse(
            id=issue.id,
            repository=issue.repository,
            title=issue.title,
            number=issue.number,
            label=issue.label or "unlabeled",
            difficulty=issue.difficulty,
            url=issue.url,
            body=issue.body,
            suitability_score=issue.suitability_score,
            updated_at=_format_time_ago(issue.updated_at),
            ai_analysis=issue.ai_analysis,
            agent_status=issue.agent_status,
            sandbox_result=json.loads(issue.sandbox_result) if issue.sandbox_result else None,
        )
        for issue in issues
    ]


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
    await db.commit()

    from app.agent_service import analyze_issue as _analyze

    try:
        result = await _analyze(
            repo_full_name=issue.repository,
            issue_number=issue.number,
            issue_title=issue.title,
            issue_body=issue.body or "",
        )
    except Exception as e:
        issue.agent_status = "analysis_failed"
        issue.ai_analysis = f"Analysis failed: {e}"
        await db.commit()
        raise HTTPException(status_code=500, detail=str(e))

    issue.ai_analysis = result["analysis"]
    issue.agent_status = "analyzed"
    await db.commit()

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
        result = await _create_pr(
            repo_full_name=issue.repository,
            issue_number=issue.number,
            pr_title=body.pr_title,
            pr_body=body.pr_body,
            file_rewrites=body.file_rewrites,
        )
        pr_record.status = "open"
        pr_record.url = result["pr_url"]
        pr_record.number = result["pr_number"]
        pr_record.branch_name = result["branch"]
        issue.agent_status = "pr_created"
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


@app.get("/api/pull-requests", response_model=list[PullRequestResponse])
async def list_pull_requests(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[PullRequestResponse]:
    query = select(PRModel).order_by(desc(PRModel.created_at)).limit(limit)
    result = await db.execute(query)
    prs = result.scalars().all()

    return [
        PullRequestResponse(
            id=pr.id,
            repository=pr.repository,
            title=pr.title,
            number=pr.number,
            url=pr.url,
            status=pr.status,
            issue_number=pr.issue_number,
            issue_url=pr.issue_url,
            ai_summary=pr.ai_summary,
            sandbox_result=json.loads(pr.sandbox_result) if pr.sandbox_result else None,
            created_at=_format_datetime(pr.created_at),
        )
        for pr in prs
    ]


@app.get("/api/features", response_model=list[FeatureSuggestionResponse])
async def list_features(
    repository: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[FeatureSuggestionResponse]:
    """List generated feature suggestions with optional filtering."""
    query = select(FeatureModel)
    if repository:
        query = query.where(FeatureModel.repository == repository)
    if category:
        query = query.where(FeatureModel.category == category)

    query = query.order_by(desc(FeatureModel.impact_score), desc(FeatureModel.created_at)).limit(limit)
    result = await db.execute(query)
    features = result.scalars().all()

    return [
        FeatureSuggestionResponse(
            id=f.id,
            repository=f.repository,
            title=f.title,
            description=f.description,
            category=f.category,
            complexity=f.complexity,
            impact_score=f.impact_score,
            implementation_plan=f.implementation_plan,
            suggested_files=json.loads(f.suggested_files) if f.suggested_files else [],
            status=f.status,
            ai_analysis=f.ai_analysis,
            pr_title=f.pr_title,
            pr_body=f.pr_body,
            sandbox_result=json.loads(f.sandbox_result) if f.sandbox_result else None,
            contribution_source=getattr(f, "contribution_source", "ai_proposed"),
            review_required=getattr(f, "review_required", True),
            created_at=_format_time_ago(f.created_at),
        )
        for f in features
    ]


@app.post("/api/repositories/{repo_full_name:path}/suggest-features", response_model=SuggestFeaturesResponse)
async def suggest_features(
    repo_full_name: str,
    db: AsyncSession = Depends(get_db),
) -> SuggestFeaturesResponse:
    """Scan a repository and prompt Ollama to generate 3-5 high-value feature proposals."""
    repo = (
        await db.execute(select(RepoModel).where(RepoModel.full_name == repo_full_name))
    ).scalar_one_or_none()
    desc = repo.description if repo else ""

    from app.agent_service import suggest_features_for_repo

    try:
        raw_suggestions = await suggest_features_for_repo(
            repo_full_name=repo_full_name,
            repo_description=desc or "",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Feature generation failed: {str(e)}")

    saved_records = []
    for s in raw_suggestions:
        record = FeatureModel(
            repository=repo_full_name,
            title=s["title"],
            description=s["description"],
            category=s.get("category", "feature"),
            complexity=s.get("complexity", "intermediate"),
            impact_score=s.get("impact_score", 75),
            implementation_plan=s.get("implementation_plan", ""),
            suggested_files=json.dumps(s.get("suggested_files", [])),
            status="suggested",
        )
        db.add(record)
        saved_records.append(record)

    await db.commit()

    # Reload records for ID and datetime formatting
    response_list = []
    for r in saved_records:
        await db.refresh(r)
        response_list.append(
            FeatureSuggestionResponse(
                id=r.id,
                repository=r.repository,
                title=r.title,
                description=r.description,
                category=r.category,
                complexity=r.complexity,
                impact_score=r.impact_score,
                implementation_plan=r.implementation_plan,
                suggested_files=json.loads(r.suggested_files) if r.suggested_files else [],
                status=r.status,
                ai_analysis=r.ai_analysis,
                pr_title=r.pr_title,
                pr_body=r.pr_body,
                contribution_source=getattr(r, "contribution_source", "ai_proposed"),
                review_required=getattr(r, "review_required", True),
                created_at=_format_time_ago(r.created_at),
            )
        )

    return SuggestFeaturesResponse(
        repository=repo_full_name,
        count=len(response_list),
        suggestions=response_list,
    )


@app.post("/api/features/{feature_id}/implement", response_model=ImplementFeatureResponse)
async def implement_feature_endpoint(
    feature_id: int,
    db: AsyncSession = Depends(get_db),
) -> ImplementFeatureResponse:
    """Implement a feature suggestion via Ollama code generation and return proposed patch."""
    feature = await db.get(FeatureModel, feature_id)
    if not feature:
        raise HTTPException(status_code=404, detail="Feature suggestion not found")

    feature.status = "implementing"
    await db.commit()

    from app.agent_service import implement_feature as _implement

    try:
        suggested_files = json.loads(feature.suggested_files) if feature.suggested_files else []
        result = await _implement(
            repo_full_name=feature.repository,
            feature_title=feature.title,
            feature_description=feature.description,
            implementation_plan=feature.implementation_plan,
            suggested_files=suggested_files,
        )
    except Exception as e:
        feature.status = "implementation_failed"
        feature.ai_analysis = f"Implementation failed: {e}"
        await db.commit()
        raise HTTPException(status_code=500, detail=str(e))

    feature.ai_analysis = result["analysis"]
    feature.pr_title = result["pr_title"]
    feature.pr_body = result["pr_body"]
    feature.patch_content = json.dumps(result["file_rewrites"])
    feature.status = "implemented"
    await db.commit()

    return ImplementFeatureResponse(
        feature_id=feature_id,
        analysis=result["analysis"],
        pr_title=result["pr_title"],
        pr_body=result["pr_body"],
        relevant_files=result["relevant_files"],
        file_rewrites=result["file_rewrites"],
    )


@app.post("/api/features/{feature_id}/create-pr", response_model=PullRequestResponse)
async def create_pr_for_feature(
    feature_id: int,
    body: CreatePRRequest,
    db: AsyncSession = Depends(get_db),
) -> PullRequestResponse:
    """Apply the approved feature patch and open a PR on GitHub."""
    feature = await db.get(FeatureModel, feature_id)
    if not feature:
        raise HTTPException(status_code=404, detail="Feature suggestion not found")

    if not body.file_rewrites:
        raise HTTPException(status_code=400, detail="No file rewrites provided")

    sandbox_result = json.loads(feature.sandbox_result) if feature.sandbox_result else None
    if not sandbox_result or sandbox_result.get("overall_status") != "passed":
        raise HTTPException(
            status_code=409,
            detail="A fully passing sandbox verification is required before creating a pull request",
        )

    pr_body_text = body.pr_body
    is_ai_proposed = getattr(feature, "contribution_source", "ai_proposed") == "ai_proposed"
    if is_ai_proposed:
        pr_body_text += (
            "\n\n---\n"
            "> **Note:** This is an AI-proposed enhancement, not a fix for a "
            "maintainer-requested issue. It may require additional review to confirm "
            "alignment with the project's roadmap and coding standards."
        )

    pr_record = PRModel(
        repository=feature.repository,
        title=body.pr_title,
        status="creating",
        patch_content="\n\n".join(
            f"### {p}\n{c}" for p, c in body.file_rewrites.items()
        ),
        ai_summary=feature.ai_analysis or feature.description,
        pr_body=pr_body_text,
        sandbox_result=feature.sandbox_result,
    )
    db.add(pr_record)
    feature.status = "creating_pr"
    await db.commit()
    await db.refresh(pr_record)

    from app.agent_service import create_feature_pull_request as _create_feature_pr

    try:
        result = await _create_feature_pr(
            repo_full_name=feature.repository,
            feature_id=feature.id,
            pr_title=body.pr_title,
            pr_body=body.pr_body,
            file_rewrites=body.file_rewrites,
        )
        pr_record.status = "open"
        pr_record.url = result["pr_url"]
        pr_record.number = result["pr_number"]
        pr_record.branch_name = result["branch"]
        feature.status = "pr_created"
    except Exception as e:
        pr_record.status = "failed"
        pr_record.error_message = str(e)
        feature.status = "pr_failed"
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


# ---------------------------------------------------------------------------
# Sandbox Verification & Auto-Healing Endpoints
# ---------------------------------------------------------------------------

@app.post("/api/sandbox/verify", response_model=SandboxVerifyResponse)
async def run_sandbox_endpoint(body: SandboxVerifyRequest) -> SandboxVerifyResponse:
    """Run isolated sandbox tests and linters on arbitrary file rewrites."""
    from app.sandbox_service import run_sandbox_validation

    try:
        result = await run_sandbox_validation(
            repo_full_name=body.repo_full_name,
            file_rewrites=body.file_rewrites,
        )
        return SandboxVerifyResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sandbox execution error: {e}")


@app.post("/api/issues/{issue_id}/sandbox-verify", response_model=SandboxVerifyResponse)
async def verify_issue_patch(
    issue_id: int,
    body: SandboxVerifyRequest,
    db: AsyncSession = Depends(get_db),
) -> SandboxVerifyResponse:
    """Run sandbox tests on proposed issue fix and persist the diagnostic results."""
    issue = await db.get(IssueModel, issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    from app.sandbox_service import run_sandbox_validation

    try:
        result = await run_sandbox_validation(
            repo_full_name=issue.repository,
            file_rewrites=body.file_rewrites,
        )
        issue.sandbox_result = json.dumps(result)
        await db.commit()
        return SandboxVerifyResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sandbox execution error: {e}")


@app.post("/api/features/{feature_id}/sandbox-verify", response_model=SandboxVerifyResponse)
async def verify_feature_code(
    feature_id: int,
    body: SandboxVerifyRequest,
    db: AsyncSession = Depends(get_db),
) -> SandboxVerifyResponse:
    """Run sandbox tests on proposed feature code and persist the diagnostic results."""
    feature = await db.get(FeatureModel, feature_id)
    if not feature:
        raise HTTPException(status_code=404, detail="Feature suggestion not found")

    from app.sandbox_service import run_sandbox_validation

    try:
        result = await run_sandbox_validation(
            repo_full_name=feature.repository,
            file_rewrites=body.file_rewrites,
        )
        feature.sandbox_result = json.dumps(result)
        await db.commit()
        return SandboxVerifyResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sandbox execution error: {e}")


@app.post("/api/sandbox/auto-heal", response_model=AutoHealResponse)
async def auto_heal_endpoint(body: AutoHealRequest) -> AutoHealResponse:
    """Send test failure diagnostics to Ollama to heal and correct the broken code."""
    from app.sandbox_service import auto_heal_code

    try:
        result = await auto_heal_code(
            repo_full_name=body.repo_full_name,
            feature_or_issue_title=body.title,
            file_rewrites=body.file_rewrites,
            sandbox_diagnostics=body.sandbox_diagnostics,
        )
        return AutoHealResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Auto-healing failed: {e}")


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