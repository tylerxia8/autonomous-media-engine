from copy import deepcopy
import unittest

from aame.qualification import identity_scope
from aame.selection import rank_campaigns
from test_qualification import NOW, evidence_packet


def candidate(name, *, fee=1500, cost=0, odds=8000, days=5):
    packet = evidence_packet()
    packet.update(marketplace="content_rewards", campaign_id=name)
    for record in (*packet["facts"].values(), *packet["permissions"].values()):
        record["scope"] = identity_scope(packet)
    packet["fixed_payment"].update(fee_usd_cents=fee, max_clearing_days=days)
    packet["facts"]["payment"]["terms"] = deepcopy(packet["fixed_payment"])
    economics = {
        **packet["facts"]["payment"],
        "payment_terms": deepcopy(packet["fixed_payment"]),
        "max_cost_cents": cost,
        "minimum_collection_probability_bps": odds,
    }
    return {"packet": packet, "economics": economics}


class SelectionTest(unittest.TestCase):
    def test_prefers_higher_cash_per_day_and_preserves_manual_handoff(self):
        report = rank_campaigns([
            candidate("slow", fee=2500, days=9),
            candidate("fast", fee=1000, days=2),
        ], now=NOW)
        self.assertEqual([row["campaign"]["campaign_id"] for row in report["ranked"]],
                         ["fast", "slow"])
        self.assertEqual(report["ranked"][0]["estimated_net_cents_floor"], 720)
        self.assertIn("submit", report["ranked"][0]["manual_actions"])
        self.assertFalse(report["live_enabled"])

    def test_allocates_no_spend_and_filters_stale_or_negative_opportunities(self):
        stale = candidate("stale")
        stale["economics"]["expires_at"] = NOW.isoformat()
        result = rank_campaigns([stale, candidate("negative", odds=0),
                                 candidate("paid", cost=1)], now=NOW)
        self.assertEqual(result["status"], "no_eligible_work")
        self.assertEqual([row["reasons"] for row in result["blocked"]],
                         [["missing_current_economics"], ["nonpositive_expected_margin"],
                          ["outside_budget"]])

    def test_terms_or_permission_changes_require_new_evidence(self):
        changed = candidate("changed")
        changed["economics"]["payment_terms"]["minimum_views"] = 100
        manual = candidate("manual")
        manual["packet"]["permissions"]["submit"]["mode"] = "automated"
        result = rank_campaigns([changed, manual], now=NOW)
        self.assertEqual([row["reasons"] for row in result["blocked"]],
                         [["economics_terms_mismatch"], ["permission:submit"]])
