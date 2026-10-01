"""Run fixed Patchwork validation cases and print machine-readable metrics."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from app.sandbox_service import run_sandbox_validation


async def run_case(case: dict[str, Any]) -> dict[str, Any]:
    result = await run_sandbox_validation(
        repo_full_name=case["repo_full_name"],
        file_rewrites=case["file_rewrites"],
        runtime=case.get("runtime"),
    )
    expected = case.get("expected_status")
    return {
        "name": case.get("name", case["repo_full_name"]),
        "repository": case["repo_full_name"],
        "status": result["overall_status"],
        "success": result["success"],
        "expected_status": expected,
        "matched_expectation": expected is None or result["overall_status"] == expected,
        "score": result["score"],
        "execution_time_seconds": result["execution_time_seconds"],
        "summary": result["summary"],
    }


async def main(path: Path) -> None:
    cases = json.loads(path.read_text())
    results = [await run_case(case) for case in cases]
    matched = sum(result["matched_expectation"] for result in results)
    print(json.dumps({
        "cases": len(results),
        "matched_expectations": matched,
        "pass_rate": round(matched / len(results) * 100, 1) if results else 0,
        "results": results,
    }, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", type=Path)
    args = parser.parse_args()
    asyncio.run(main(args.cases))