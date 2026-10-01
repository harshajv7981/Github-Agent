from datetime import datetime
from sqlalchemy import String, Integer, Text, DateTime, Boolean, Enum
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    owner: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, nullable=True)
    language: Mapped[str] = mapped_column(String(50), nullable=True)
    stars: Mapped[int] = mapped_column(Integer, default=0)
    open_issues: Mapped[int] = mapped_column(Integer, default=0)
    fit_score: Mapped[int] = mapped_column(Integer, default=0)
    trend_percent: Mapped[int] = mapped_column(Integer, default=0)
    url: Mapped[str] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_scanned_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class Issue(Base):
    __tablename__ = "issues"

    id: Mapped[int] = mapped_column(primary_key=True)
    repository: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str] = mapped_column(Text)
    number: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(100), nullable=True)
    difficulty: Mapped[str] = mapped_column(
        Enum("good_first_issue", "intermediate", name="difficulty_enum")
    )
    url: Mapped[str] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text, nullable=True)
    suitability_score: Mapped[int] = mapped_column(Integer, default=0)
    is_suitable: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_analysis: Mapped[str] = mapped_column(Text, nullable=True)
    agent_status: Mapped[str] = mapped_column(String(50), nullable=True)
    sandbox_result: Mapped[str] = mapped_column(Text, nullable=True)  # JSON encoded test & lint results
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(
        Enum("running", "completed", "failed", "needs_review", name="run_status_enum")
    )
    summary: Mapped[str] = mapped_column(Text, nullable=True)
    repositories_scanned: Mapped[int] = mapped_column(Integer, default=0)
    issues_found: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PullRequest(Base):
    __tablename__ = "pull_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    repository: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str] = mapped_column(Text)
    number: Mapped[int] = mapped_column(Integer, nullable=True)
    url: Mapped[str] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending_review")
    branch_name: Mapped[str] = mapped_column(String(200), nullable=True)
    issue_number: Mapped[int] = mapped_column(Integer, nullable=True)
    issue_url: Mapped[str] = mapped_column(String(500), nullable=True)
    patch_content: Mapped[str] = mapped_column(Text, nullable=True)
    patch_file: Mapped[str] = mapped_column(String(500), nullable=True)
    ai_summary: Mapped[str] = mapped_column(Text, nullable=True)
    pr_body: Mapped[str] = mapped_column(Text, nullable=True)
    sandbox_result: Mapped[str] = mapped_column(Text, nullable=True)  # JSON encoded test & lint results
    error_message: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class FeatureSuggestion(Base):
    __tablename__ = "feature_suggestions"

    id: Mapped[int] = mapped_column(primary_key=True)
    repository: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(50), default="feature")
    complexity: Mapped[str] = mapped_column(String(50), default="intermediate")
    impact_score: Mapped[int] = mapped_column(Integer, default=75)
    implementation_plan: Mapped[str] = mapped_column(Text)
    suggested_files: Mapped[str] = mapped_column(Text, default="[]")  # JSON encoded list
    status: Mapped[str] = mapped_column(String(50), default="suggested")
    ai_analysis: Mapped[str] = mapped_column(Text, nullable=True)
    patch_content: Mapped[str] = mapped_column(Text, nullable=True)  # JSON encoded rewrites
    pr_title: Mapped[str] = mapped_column(String(255), nullable=True)
    pr_body: Mapped[str] = mapped_column(Text, nullable=True)
    sandbox_result: Mapped[str] = mapped_column(Text, nullable=True)  # JSON encoded test & lint results
    contribution_source: Mapped[str] = mapped_column(String(30), default="ai_proposed")  # ai_proposed | maintainer_requested
    review_required: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
