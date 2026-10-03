import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ci_agent import approve_ci_repair as _approve_ci_repair
from app.ci_agent import propose_ci_repair as _propose_ci_repair
from app.database import get_db
from app.github_service import GitHubService
from app.models import PullRequest as PRModel
from app.schemas import AgentApprovalRequest, CIStatusResponse, PullRequestResponse

router = APIRouter()

def _format_datetime(value: datetime | None) -> str:
    return value.isoformat() if value else ""

@router.get("/api/pull-requests", response_model=list[PullRequestResponse])
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


@router.get("/api/pull-requests/{pull_request_id}/ci-status", response_model=CIStatusResponse)
async def pull_request_ci_status(
    pull_request_id: int,
    db: AsyncSession = Depends(get_db),
) -> CIStatusResponse:
    """Read the latest GitHub Actions/check-run state for a tracked pull request."""
    record = await db.get(PRModel, pull_request_id)
    if not record or not record.number:
        raise HTTPException(status_code=404, detail="Pull request or GitHub number not found")

    from app.github_service import GitHubService

    try:
        checks = await asyncio.to_thread(
            GitHubService().get_pull_request_checks,
            record.repository,
            record.number,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Unable to read GitHub checks: {exc}") from exc

    return CIStatusResponse(**checks)


@router.post("/api/pull-requests/{pull_request_id}/ci-repair")
async def propose_ci_repair(
    pull_request_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Diagnose failed CI and create an approval-gated repair proposal."""
    from app.ci_agent import propose_ci_repair as _propose_ci_repair

    try:
        return await _propose_ci_repair(db, pull_request_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("CI repair proposal failed pull_request_id=%s", pull_request_id)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/api/pull-requests/{pull_request_id}/ci-repair/approve")
async def approve_ci_repair(
    pull_request_id: int,
    body: AgentApprovalRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Commit a reviewed CI repair proposal to the existing PR branch."""
    from app.ci_agent import approve_ci_repair as _approve_ci_repair

    try:
        return await _approve_ci_repair(db, pull_request_id, body.reviewer)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("CI repair approval failed pull_request_id=%s", pull_request_id)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


