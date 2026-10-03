import asyncio
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.feature_agent import create_feature_pull_request, implement_feature, suggest_features_for_repo
from app.database import get_db
from app.models import FeatureSuggestion as FeatureModel, PullRequest as PRModel
from app.schemas import (
    CreatePRRequest,
    FeatureSuggestionResponse,
    ImplementFeatureResponse,
    PullRequestResponse,
    SuggestFeaturesResponse,
)

router = APIRouter()

def _format_datetime(value: datetime | None) -> str:
    return value.isoformat() if value else ""


def _format_time_ago(value: datetime) -> str:
    from datetime import timezone

    now = datetime.now(timezone.utc)
    current = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    delta = now - current
    if delta.days > 0:
        return f"{delta.days} day{'s' if delta.days > 1 else ''} ago"
    hours = delta.seconds // 3600
    if hours > 0:
        return f"{hours} hour{'s' if hours > 1 else ''} ago"
    minutes = (delta.seconds % 3600) // 60
    return f"{minutes} minute{'s' if minutes > 1 else ''} ago" if minutes else "just now"

@router.get("/api/features", response_model=list[FeatureSuggestionResponse])
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


@router.post("/api/repositories/{repo_full_name:path}/suggest-features", response_model=SuggestFeaturesResponse)
async def suggest_features(
    repo_full_name: str,
    db: AsyncSession = Depends(get_db),
) -> SuggestFeaturesResponse:
    """Scan a repository and prompt Ollama to generate 3-5 high-value feature proposals."""
    repo = (
        await db.execute(select(RepoModel).where(RepoModel.full_name == repo_full_name))
    ).scalar_one_or_none()
    desc = repo.description if repo else ""

    from app.feature_agent import suggest_features_for_repo

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


@router.post("/api/features/{feature_id}/implement", response_model=ImplementFeatureResponse)
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

    from app.feature_agent import implement_feature as _implement

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


@router.post("/api/features/{feature_id}/create-pr", response_model=PullRequestResponse)
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

    from app.feature_agent import create_feature_pull_request as _create_feature_pr

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


