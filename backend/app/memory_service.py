"""Structured repository memory used to ground future contribution runs."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentMemoryFact


async def remember(
    session: AsyncSession,
    repository: str,
    kind: str,
    content: str,
    *,
    confidence: int = 70,
    source: str = "agent",
) -> AgentMemoryFact:
    if not content.strip():
        raise ValueError("Memory content cannot be empty")
    confidence = max(0, min(100, confidence))
    fact = AgentMemoryFact(
        repository=repository,
        kind=kind.strip()[:50],
        content=content.strip()[:10_000],
        confidence=confidence,
        source=source.strip()[:100],
    )
    session.add(fact)
    await session.flush()
    return fact


async def context_for(
    session: AsyncSession,
    repository: str,
    *,
    limit: int = 20,
) -> str:
    facts = (
        await session.scalars(
            select(AgentMemoryFact)
            .where(AgentMemoryFact.repository == repository)
            .order_by(AgentMemoryFact.confidence.desc(), AgentMemoryFact.updated_at.desc())
            .limit(limit)
        )
    ).all()
    if not facts:
        return "(No repository-specific memory is available.)"
    return "\n".join(
        f"- [{fact.kind}; confidence={fact.confidence}] {fact.content}"
        for fact in facts
    )
