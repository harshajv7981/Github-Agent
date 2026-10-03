import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import FeatureSuggestion as FeatureModel, Issue as IssueModel
from app.schemas import AutoHealRequest, AutoHealResponse, SandboxVerifyRequest, SandboxVerifyResponse

router = APIRouter()

# ---------------------------------------------------------------------------
# Sandbox Verification & Auto-Healing Endpoints
# ---------------------------------------------------------------------------

@router.post("/api/sandbox/verify", response_model=SandboxVerifyResponse)
async def run_sandbox_endpoint(body: SandboxVerifyRequest) -> SandboxVerifyResponse:
    """Verify proposed code and automatically repair failures in isolation."""
    from app.sandbox_service import run_sandbox_validation_with_auto_heal

    try:
        result = await run_sandbox_validation_with_auto_heal(
            repo_full_name=body.repo_full_name,
            title=f"Sandbox validation for {body.repo_full_name}",
            file_rewrites=body.file_rewrites,
            runtime=body.runtime,
            terminal_command=body.terminal_command,
        )
        return SandboxVerifyResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sandbox execution error: {e}")


@router.post("/api/issues/{issue_id}/sandbox-verify", response_model=SandboxVerifyResponse)
async def verify_issue_patch(
    issue_id: int,
    body: SandboxVerifyRequest,
    db: AsyncSession = Depends(get_db),
) -> SandboxVerifyResponse:
    """Run sandbox tests on proposed issue fix and persist the diagnostic results."""
    issue = await db.get(IssueModel, issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    from app.sandbox_service import run_sandbox_validation_with_auto_heal

    try:
        result = await run_sandbox_validation_with_auto_heal(
            repo_full_name=issue.repository,
            title=issue.title,
            file_rewrites=body.file_rewrites,
            runtime=body.runtime,
            terminal_command=body.terminal_command,
        )
        issue.sandbox_result = json.dumps(result)
        await db.commit()
        return SandboxVerifyResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sandbox execution error: {e}")


@router.post("/api/features/{feature_id}/sandbox-verify", response_model=SandboxVerifyResponse)
async def verify_feature_code(
    feature_id: int,
    body: SandboxVerifyRequest,
    db: AsyncSession = Depends(get_db),
) -> SandboxVerifyResponse:
    """Run sandbox tests on proposed feature code and persist the diagnostic results."""
    feature = await db.get(FeatureModel, feature_id)
    if not feature:
        raise HTTPException(status_code=404, detail="Feature suggestion not found")

    from app.sandbox_service import run_sandbox_validation_with_auto_heal

    try:
        result = await run_sandbox_validation_with_auto_heal(
            repo_full_name=feature.repository,
            title=feature.title,
            file_rewrites=body.file_rewrites,
            runtime=body.runtime,
            terminal_command=body.terminal_command,
        )
        feature.sandbox_result = json.dumps(result)
        await db.commit()
        return SandboxVerifyResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sandbox execution error: {e}")


@router.post("/api/sandbox/auto-heal", response_model=AutoHealResponse)
async def auto_heal_endpoint(body: AutoHealRequest) -> AutoHealResponse:
    """Send test failure diagnostics to Ollama to heal and correct the broken code."""
    from app.sandbox_service import auto_heal_code

    try:
        result = await auto_heal_code(
            repo_full_name=body.repo_full_name,
            feature_or_issue_title=body.title,
            file_rewrites=body.file_rewrites,
            sandbox_diagnostics=body.sandbox_diagnostics,
            terminal_command=body.terminal_command,
        )
        return AutoHealResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Auto-healing failed: {e}")


