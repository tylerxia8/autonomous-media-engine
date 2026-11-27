from copy import deepcopy
from datetime import datetime, timezone
import unittest

from aame.qualification import ACTIONS, FACTS, content_rewards_template, qualify


NOW = datetime(2026, 11, 26, tzinfo=timezone.utc)


def evidence_packet():
    identity = {
        "campaign_id": "synthetic-pilot",
        "version": "1",
        "platform": "youtube",
        "account_id": "synthetic-channel",
        "asset_id": "synthetic-asset",
    }
    payment = {
        "fee_usd_cents": 1500,
        "max_deductions_usd_cents": 100,
        "minimum_views": 0,
        "max_clearing_days": 5,
        "review_order": "post_only",
        "submission_deadline_rule": "30 minutes after posting",
        "withdrawal_terms": "Synthetic bank payout evidence",
    }
    evidence = {
        "reference": "synthetic-evidence",
        "reviewer": "fixture-reviewer",
        "verified": True,
        "observed_at": "2026-11-25T00:00:00Z",
        "expires_at": "2026-11-27T00:00:00Z",
        "scope": identity,
    }
    return {
        **identity,
        "fixed_payment": payment,
        "facts": {
            **{fact: dict(evidence) for fact in FACTS},
            "payment": {**evidence, "terms": deepcopy(payment)},
        },
        "permissions": {
            action: {**evidence, "action": action, "mode": "manual"}
            for action in ACTIONS
            if action != "read_metrics"
        },
    }


class QualificationTest(unittest.TestCase):
    def test_complete_synthetic_route_requires_manual_submission(self):
        result = qualify(evidence_packet(), NOW)
        self.assertEqual(result["status"], "evidence_complete")
        self.assertEqual(result["capabilities"]["submit"], "manual")
        self.assertEqual(result["capabilities"]["read_metrics"], "disabled")
        self.assertFalse(result["live_enabled"])

    def test_marketplace_template_is_blocked_and_automated_submission_is_disabled(self):
        blank = content_rewards_template("candidate")
        self.assertEqual(qualify(blank, NOW)["status"], "blocked")
        packet = evidence_packet()
        packet["marketplace"] = "content_rewards"
        for record in (*packet["facts"].values(), *packet["permissions"].values()):
            record["scope"]["marketplace"] = "content_rewards"
        self.assertEqual(qualify(packet, NOW)["status"], "evidence_complete")
        packet["permissions"]["submit"]["mode"] = "automated"
        result = qualify(packet, NOW)
        self.assertIn("permission:submit", result["blockers"])
        self.assertEqual(result["capabilities"]["submit"], "disabled")

    def test_every_missing_fact_disables_all_actions(self):
        for fact in FACTS:
            with self.subTest(fact=fact):
                packet = evidence_packet()
                del packet["facts"][fact]
                result = qualify(packet, NOW)
                self.assertIn(fact, result["blockers"])
                self.assertEqual(set(result["capabilities"].values()), {"disabled"})

    def test_invalid_submission_grants_cannot_authorize_action(self):
        for changes in (
            {"action": "publish"},
            {"expires_at": NOW.isoformat()},
            {"observed_at": "2026-11-26T12:00:00Z"},
            {"scope": {"version": "wrong"}},
            {"verified": "true"},
            {"mode": "unknown"},
        ):
            with self.subTest(changes=changes):
                packet = evidence_packet()
                packet["permissions"]["submit"].update(changes)
                result = qualify(packet, NOW)
                self.assertIn("permission:submit", result["blockers"])
                self.assertEqual(result["capabilities"]["submit"], "disabled")

    def test_terms_changes_invalidate_payment_evidence(self):
        packet = evidence_packet()
        packet["fixed_payment"]["fee_usd_cents"] += 1
        self.assertIn("payment_terms_mismatch", qualify(packet, NOW)["blockers"])

    def test_invalid_payment_and_missing_identity_block_route(self):
        packet = evidence_packet()
        del packet["account_id"]
        packet["fixed_payment"]["minimum_views"] = 10
        result = qualify(packet, NOW)
        self.assertIn("incomplete_identity", result["blockers"])
        self.assertIn("incomplete_fixed_payment", result["blockers"])


if __name__ == "__main__":
    unittest.main()
