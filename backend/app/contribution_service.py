"""Deterministic contribution-readiness scoring built from GitHub policy signals."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def score_issue_acceptance(
    issue: dict[str, Any],
    preflight: dict[str, Any],
) -> dict[str, Any]:
    score = 70
    reasons: list[str] = []
    blockers = preflight.get("blockers", [])
    warnings = preflight.get("warnings", [])

    if blockers:
        score -= min(60, len(blockers) * 30)
        reasons.extend(f"Blocker: {item}" for item in blockers)
    if warnings:
        score -= min(25, len(warnings) * 8)
        reasons.extend(f"Warning: {item}" for item in warnings)

    if issue.get("difficulty") == "good_first_issue":
        score += 10
        reasons.append("Issue is explicitly marked as beginner-friendly.")
    if issue.get("label") in {"help wanted", "good first issue", "good-first-issue"}:
        score += 5
    if issue.get("body"):
        score += 5
    else:
        score -= 15
        reasons.append("Issue has no description; clarification is recommended.")

    score = max(0, min(100, score))
    if blockers:
        recommendation = "Do not submit; resolve the blocker first."
    elif score >= 75:
        recommendation = "Good candidate for a reviewed contribution."
    elif score >= 50:
        recommendation = "Clarify repository expectations before coding."
    else:
        recommendation = "Avoid automated contribution for now."

    return {
        "score": score,
        "recommendation": recommendation,
        "reasons": reasons,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def rank_issue_candidates(issues: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    """Rank actionable issues without allowing an active run to be selected again."""
    ranked: list[dict[str, Any]] = []
    for issue in issues:
        reasons: list[str] = []
        if issue.get("agent_status") in {"analyzing", "running", "awaiting_approval"}:
            continue
        score = int(issue.get("suitability_score") or 0)
        if issue.get("is_suitable"):
            score += 10
            reasons.append("Passed the repository suitability threshold.")
        if issue.get("difficulty") == "good_first_issue":
            score += 8
            reasons.append("Has a good-first-issue difficulty signal.")
        if issue.get("body"):
            score += 5
            reasons.append("Contains issue context for planning.")
        else:
            score -= 20
            reasons.append("Missing issue context; clarification is needed.")
        if issue.get("ai_analysis"):
            score += 3
            reasons.append("Already has an analysis checkpoint.")
        score = max(0, min(100, score))
        ranked.append({**issue, "selection_score": score, "selection_reasons": reasons})
    ranked.sort(key=lambda item: (-item["selection_score"], item.get("updated_at") or ""))
    return ranked[: max(0, limit)]