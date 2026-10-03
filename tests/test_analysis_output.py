import re
import unittest

from app.agent_service import _clean_analysis_text
from app.contribution_service import rank_issue_candidates


class AnalysisOutputTests(unittest.TestCase):
    def test_rejects_reasoning_token_garbage(self):
        raw = "_popip6z6z6z6z6z6z6z6z6z6z6z6z6z6z6z6z6z6z6z6z6z6z6z"

        result = _clean_analysis_text(raw, None)

        self.assertIn("malformed reasoning", result)

    def test_keeps_bounded_analysis_section(self):
        match = re.search(r"ANALYSIS:([\s\S]+)", "ANALYSIS:\nFixed the import.")

        self.assertEqual(_clean_analysis_text("ignored", match), "Fixed the import.")

    def test_candidate_ranking_excludes_active_runs_and_explains_score(self):
        ranked = rank_issue_candidates([
            {
                "id": 1,
                "title": "clear issue",
                "suitability_score": 80,
                "is_suitable": True,
                "difficulty": "good_first_issue",
                "body": "Details",
                "agent_status": None,
            },
            {
                "id": 2,
                "title": "already running",
                "suitability_score": 100,
                "is_suitable": True,
                "agent_status": "running",
            },
        ])

        self.assertEqual([item["id"] for item in ranked], [1])
        self.assertTrue(ranked[0]["selection_reasons"])