from typing import Literal, Optional

from pydantic import BaseModel


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
    selection_score: Optional[int] = None
    selection_reasons: list[str] = []


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
    provider: str


class DiscoveryTriggerResponse(BaseModel):
    message: str
    run_id: int


class AgentRunRequest(BaseModel):
    issue_id: int
    idempotency_key: Optional[str] = None


class AgentRunResponse(BaseModel):
    id: int
    issue_id: Optional[int]
    repository: Optional[str]
    status: str
    current_step: str
    attempt: int
    model_requests: int
    estimated_tokens: int
    failure_reason: Optional[str]


class AgentRunListResponse(AgentRunResponse):
    issue_title: Optional[str] = None
    issue_number: Optional[int] = None
    created_at: str
    updated_at: str


class AgentApprovalRequest(BaseModel):
    reviewer: str


class AgentMemoryFactRequest(BaseModel):
    kind: str
    content: str
    confidence: int = 70
    source: str = "user"


class AgentMemoryFactResponse(BaseModel):
    id: int
    repository: str
    kind: str
    content: str
    confidence: int
    source: str


class AgentReviewFindingResponse(BaseModel):
    id: int
    decision: str
    summary: str
    severity: str
    file_path: str
    explanation: str
    suggested_fix: Optional[str]


class AgentStepResponse(BaseModel):
    id: int
    step_key: str
    status: str
    attempt: int
    input: dict
    output: dict
    error: Optional[str]


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


class CIStatusResponse(BaseModel):
    repository: str
    pull_request_number: int
    commit_sha: str
    state: Optional[str]
    total_checks: int
    passed_checks: int
    failed_checks: int
    checks: list[dict]
    ready_for_review: bool


class RepositoryIntelligenceResponse(BaseModel):
    repository: str
    files_scanned: int
    symbol_count: int
    test_file_count: int
    modules: list[dict]
    symbols: list[dict]
    imports: list[dict]
    dependency_edges: list[dict]
    test_files: list[str]


class AcceptanceScoreResponse(BaseModel):
    issue_id: int
    repository: str
    issue_number: int
    score: int
    recommendation: str
    reasons: list[str]
    checked_at: str


class AgentEventResponse(BaseModel):
    id: int
    event_type: str
    payload: dict
    created_at: str


class RepositoryMemoryRequest(BaseModel):
    memory: str


class RepositoryMemoryResponse(BaseModel):
    repository: str
    memory: str
    updated_at: str


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
    runtime: Optional[Literal["process", "docker"]] = None
    terminal_command: Optional[list[str]] = None


class SandboxVerifyResponse(BaseModel):
    success: bool
    overall_status: str
    score: int
    execution_time_seconds: float
    environment: str
    checks: dict
    summary: str
    modified_files: list[str]
    file_rewrites: Optional[dict[str, str]] = None
    healing_analysis: Optional[str] = None
    healed: Optional[bool] = None
    healing_attempts: Optional[int] = None
    healing_history: Optional[list[dict]] = None


class RegressionTestResponse(BaseModel):
    issue_id: int
    test_path: str
    test_content: str
    explanation: str
    before_result: SandboxVerifyResponse
    fails_before_patch: bool


class AutoHealRequest(BaseModel):
    repo_full_name: str
    title: str
    file_rewrites: dict[str, str]
    sandbox_diagnostics: dict
    terminal_command: Optional[list[str]] = None


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
