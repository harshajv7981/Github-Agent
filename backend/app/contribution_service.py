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