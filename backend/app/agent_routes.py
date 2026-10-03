import asyncio
import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contribution_agent import ContributionAgent
from app.database import AsyncSessionLocal, get_db
from app.memory_service import remember
from app.models import AgentMemoryFact, AgentReviewFinding, AgentRun, AgentStep, Issue
from app.schemas import (
    AgentApprovalRequest,
    AgentMemoryFactRequest,
    AgentMemoryFactResponse,
    AgentReviewFindingResponse,
    AgentRunRequest,
    AgentRunListResponse,
    AgentRunResponse,
    AgentStepResponse,
    PullRequestResponse,
)

router = APIRouter(prefix="/api")


def _format_datetime(value: datetime | None) -> str:
    return value.isoformat() if value else ""


def _agent_run_response(run: AgentRun) -> AgentRunResponse:
    return AgentRunResponse(
        id=run.id,
        issue_id=run.issue_id,
        repository=run.repository,
        status=run.status,
        current_step=run.current_step,
        attempt=run.attempt,
        model_requests=run.model_requests,
        estimated_tokens=run.estimated_tokens,
        failure_reason=run.failure_reason,
    )


async def _execute_agent_run(run_id: int) -> None:
    async with AsyncSessionLocal() as session:
        await ContributionAgent(session).execute(run_id)


@router.get("/agent-runs", response_model=list[AgentRunListResponse])
async def list_agent_runs(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
) -> list[AgentRunListResponse]:
    rows = (
        await db.execute(
            select(AgentRun, Issue.title, Issue.number)
            .outerjoin(Issue, Issue.id == AgentRun.issue_id)
            .order_by(desc(AgentRun.created_at))
            .limit(min(max(limit, 1), 100))
        )
    ).all()
    return [
        AgentRunListResponse(
            **_agent_run_response(run).model_dump(),
            issue_title=issue_title,
            issue_number=issue_number,
            created_at=_format_datetime(run.created_at),
            updated_at=_format_datetime(run.updated_at),
        )
        for run, issue_title, issue_number in rows
    ]


@router.post("/agent-runs", response_model=AgentRunResponse, status_code=202)
async def start_agent_run(
    body: AgentRunRequest,
    db: AsyncSession = Depends(get_db),
) -> AgentRunResponse:
    idempotency_key = body.idempotency_key or f"issue:{body.issue_id}:{uuid.uuid4()}"
    try:
        run = await ContributionAgent(db).start(body.issue_id, idempotency_key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if run.status in {"queued", "failed"}:
        asyncio.create_task(_execute_agent_run(run.id))
    return _agent_run_response(run)


@router.post("/agent-runs/next", response_model=AgentRunResponse, status_code=202)
async def start_next_agent_run(db: AsyncSession = Depends(get_db)) -> AgentRunResponse:
    from app.contribution_service import rank_issue_candidates
    from app.models import Issue as IssueModel

    active_issue_ids = {
        issue_id
        for issue_id in (
            await db.scalars(
                select(AgentRun.issue_id).where(
                    AgentRun.status.notin_(["completed", "failed", "cancelled"]),
                    AgentRun.issue_id.isnot(None),
                )
            )
        ).all()
    }
    issues = (
        await db.scalars(
            select(IssueModel)
            .where(IssueModel.is_suitable == True)
            .order_by(desc(IssueModel.suitability_score))
            .limit(100)
        )
    ).all()
    candidates = rank_issue_candidates(
        [
            {
                "id": issue.id,
                "repository": issue.repository,
                "title": issue.title,
                "number": issue.number,
                "difficulty": issue.difficulty,
                "body": issue.body,
                "suitability_score": issue.suitability_score,
                "is_suitable": issue.is_suitable,
                "agent_status": issue.agent_status,
                "updated_at": issue.updated_at.isoformat() if issue.updated_at else "",
            }
            for issue in issues
            if issue.id not in active_issue_ids
        ],
        limit=1,
    )
    if not candidates:
        raise HTTPException(status_code=404, detail="No unclaimed actionable issue is available")
    run = await ContributionAgent(db).start(
        candidates[0]["id"], f"autonomous:issue:{candidates[0]['id']}"
    )
    asyncio.create_task(_execute_agent_run(run.id))
    return _agent_run_response(run)


@router.get("/agent-runs/{run_id}", response_model=AgentRunResponse)
async def get_agent_run(run_id: int, db: AsyncSession = Depends(get_db)) -> AgentRunResponse:
    run = await db.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return _agent_run_response(run)


@router.get("/agent-runs/{run_id}/findings", response_model=list[AgentReviewFindingResponse])
async def get_agent_review_findings(
    run_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[AgentReviewFindingResponse]:
    findings = (
        await db.scalars(
            select(AgentReviewFinding)
            .where(AgentReviewFinding.run_id == run_id)
            .order_by(AgentReviewFinding.id)
        )
    ).all()
    return [
        AgentReviewFindingResponse(
            id=finding.id,
            decision=finding.decision,
            summary=finding.summary,
            severity=finding.severity,
            file_path=finding.file_path,
            explanation=finding.explanation,
            suggested_fix=finding.suggested_fix,
        )
        for finding in findings
    ]


@router.get("/agent-runs/{run_id}/steps", response_model=list[AgentStepResponse])
async def get_agent_steps(run_id: int, db: AsyncSession = Depends(get_db)) -> list[AgentStepResponse]:
    steps = (
        await db.scalars(select(AgentStep).where(AgentStep.run_id == run_id).order_by(AgentStep.id))
    ).all()
    return [
        AgentStepResponse(
            id=step.id,
            step_key=step.step_key,
            status=step.status,
            attempt=step.attempt,
            input=json.loads(step.input_json or "{}"),
            output=json.loads(step.output_json or "{}"),
            error=step.error,
        )
        for step in steps
    ]


@router.post("/agent-runs/{run_id}/resume", response_model=AgentRunResponse, status_code=202)
async def resume_agent_run(run_id: int, db: AsyncSession = Depends(get_db)) -> AgentRunResponse:
    run = await db.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    if run.status not in {"failed", "queued"}:
        raise HTTPException(status_code=409, detail=f"Run is not resumable from {run.status}")
    asyncio.create_task(_execute_agent_run(run.id))
    return _agent_run_response(run)


@router.get("/repositories/{repo_full_name:path}/memory-facts", response_model=list[AgentMemoryFactResponse])
async def get_memory_facts(
    repo_full_name: str,
    db: AsyncSession = Depends(get_db),
) -> list[AgentMemoryFactResponse]:
    facts = (
        await db.scalars(
            select(AgentMemoryFact)
            .where(AgentMemoryFact.repository == repo_full_name)
            .order_by(AgentMemoryFact.confidence.desc(), AgentMemoryFact.updated_at.desc())
        )
    ).all()
    return [
        AgentMemoryFactResponse(
            id=fact.id,
            repository=fact.repository,
            kind=fact.kind,
            content=fact.content,
            confidence=fact.confidence,
            source=fact.source,
        )
        for fact in facts
    ]


@router.post("/repositories/{repo_full_name:path}/memory-facts", response_model=AgentMemoryFactResponse)
async def add_memory_fact(
    repo_full_name: str,
    body: AgentMemoryFactRequest,
    db: AsyncSession = Depends(get_db),
) -> AgentMemoryFactResponse:
    try:
        fact = await remember(
            db,
            repo_full_name,
            body.kind,
            body.content,
            confidence=body.confidence,
            source=body.source,
        )
        await db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AgentMemoryFactResponse(
        id=fact.id,
        repository=fact.repository,
        kind=fact.kind,
        content=fact.content,
        confidence=fact.confidence,
        source=fact.source,
    )


@router.post("/agent-runs/{run_id}/approve-pr", response_model=PullRequestResponse)
async def approve_agent_pr(
    run_id: int,
    body: AgentApprovalRequest,
    db: AsyncSession = Depends(get_db),
) -> PullRequestResponse:
    try:
        pr = await ContributionAgent(db).approve_pr(run_id, body.reviewer)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return PullRequestResponse(
        id=pr.id,
        repository=pr.repository,
        title=pr.title,
        number=pr.number,
        url=pr.url,
        status=pr.status,
        issue_number=pr.issue_number,
        issue_url=pr.issue_url,
        ai_summary=pr.ai_summary,
        sandbox_result=None,
        created_at=_format_datetime(pr.created_at),
    )
