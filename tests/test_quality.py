from __future__ import annotations

import unittest

from agentloop.quality import evaluate_gate


class QualityGateTests(unittest.TestCase):
    def test_approved_review_with_null_test_exit_code_requires_changes(self) -> None:
        state = {
            "acceptance_criteria": [
                {
                    "id": "AC-1",
                    "required": True,
                    "status": "pending",
                    "verification": "automated_test",
                }
            ]
        }
        review = {
            "decision": "APPROVED",
            "open_medium_high_count": 0,
            "acceptance_results": [{"criteria_id": "AC-1", "status": "passed"}],
            "test_results": [{"command": "python -m pytest", "exit_code": None}],
        }

        self.assertEqual(evaluate_gate(state, review), "CHANGES_REQUIRED")

    def test_approved_review_with_required_automated_test_needs_passing_test(self) -> None:
        state = {
            "acceptance_criteria": [
                {
                    "id": "AC-1",
                    "required": True,
                    "status": "pending",
                    "verification": "unit_test",
                }
            ]
        }
        review = {
            "decision": "APPROVED",
            "open_medium_high_count": 0,
            "acceptance_results": [{"criteria_id": "AC-1", "status": "passed"}],
            "test_results": [],
        }

        self.assertEqual(evaluate_gate(state, review), "CHANGES_REQUIRED")

    def test_approved_review_with_passing_test_is_approved(self) -> None:
        state = {
            "acceptance_criteria": [
                {
                    "id": "AC-1",
                    "required": True,
                    "status": "pending",
                    "verification": "unit_test",
                }
            ]
        }
        review = {
            "decision": "APPROVED",
            "open_medium_high_count": 0,
            "acceptance_results": [{"criteria_id": "AC-1", "status": "passed"}],
            "test_results": [{"command": "python -m pytest", "exit_code": 0}],
        }

        self.assertEqual(evaluate_gate(state, review), "APPROVED")

    def test_manual_only_acceptance_can_approve_without_test_results(self) -> None:
        state = {
            "acceptance_criteria": [
                {
                    "id": "AC-1",
                    "required": True,
                    "status": "pending",
                    "verification": "functional_review",
                }
            ]
        }
        review = {
            "decision": "APPROVED",
            "open_medium_high_count": 0,
            "acceptance_results": [{"criteria_id": "AC-1", "status": "passed"}],
            "test_results": [],
        }

        self.assertEqual(evaluate_gate(state, review), "APPROVED")


if __name__ == "__main__":
    unittest.main()
