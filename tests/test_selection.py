from copy import deepcopy
import unittest

from aame.qualification import (DIRECT_AUTOMATED, PRIVATE_PLATFORM, direct_pilot_template,
                                identity_scope, qualify)
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
        ], now=NOW, route="content_rewards")
        self.assertEqual([row["campaign"]["campaign_id"] for row in report["ranked"]],
                         ["fast", "slow"])
        self.assertEqual(report["ranked"][0]["estimated_net_cents_floor"], 720)
        self.assertIn("submit", report["ranked"][0]["manual_actions"])
        self.assertFalse(report["live_enabled"])

    def test_allocates_no_spend_and_filters_stale_or_negative_opportunities(self):
        stale = candidate("stale")
        stale["economics"]["expires_at"] = NOW.isoformat()
        result = rank_campaigns([stale, candidate("negative", odds=0),
                                 candidate("paid", cost=1)], now=NOW, route="content_rewards")
        self.assertEqual(result["status"], "no_eligible_work")
        self.assertEqual([row["reasons"] for row in result["blocked"]],
                         [["missing_current_economics"], ["nonpositive_expected_margin"],
                          ["outside_budget"]])

    def test_terms_or_permission_changes_require_new_evidence(self):
        changed = candidate("changed")
        changed["economics"]["payment_terms"]["minimum_views"] = 100
        manual = candidate("manual")
        manual["packet"]["permissions"]["submit"]["mode"] = "automated"
        result = rank_campaigns([changed, manual], now=NOW, route="content_rewards")
        self.assertEqual([row["reasons"] for row in result["blocked"]],
                         [["economics_terms_mismatch"], ["permission:submit"]])


class DirectSelectionTest(unittest.TestCase):
    def make_direct(self):
        lead = candidate("direct-pilot")
        packet = lead["packet"]
        packet["marketplace"] = "direct"
        scope = identity_scope(packet)
        for record in (*packet["facts"].values(), *packet["permissions"].values(), lead["economics"]):
            record["scope"] = scope
        for action in DIRECT_AUTOMATED:
            packet["permissions"][action]["mode"] = "automated"
        packet["facts"]["direct_agreement"] = {
            **packet["facts"]["payment"],
            "fixed_payment": deepcopy(packet["fixed_payment"]),
            "payer_ref": "fixture-payer",
            "authorized_feed_ref": "fixture-feed",
            "automated_delivery_ref": "fixture-delivery",
            "settlement_feed_ref": "fixture-settlement",
            "routine_human_review_required": False,
        }
        return lead

    def test_direct_default_does_not_fall_back_to_marketplace(self):
        report = rank_campaigns([candidate("marketplace"), self.make_direct()], now=NOW)
        self.assertEqual(report["ranked"][0]["campaign"]["campaign_id"], "direct-pilot")
        self.assertEqual(report["blocked"][0]["reasons"], ["unsupported_route"])
        self.assertFalse(report["live_enabled"])

    def test_missing_agreement_and_manual_delivery_block(self):
        missing = self.make_direct()
        missing["packet"]["facts"]["direct_agreement"]["settlement_feed_ref"] = None
        result = rank_campaigns([missing], now=NOW)
        self.assertIn("direct_agreement", result["blocked"][0]["reasons"])
        manual = self.make_direct()
        manual["packet"]["permissions"]["submit"]["mode"] = "manual"
        result = rank_campaigns([manual], now=NOW)
        self.assertIn("direct_requires_automation:submit", result["blocked"][0]["reasons"])

    def make_private(self):
        lead = self.make_direct()
        packet = lead["packet"]
        packet["platform"] = PRIVATE_PLATFORM
        scope = identity_scope(packet)
        for record in (*packet["facts"].values(), *packet["permissions"].values(), lead["economics"]):
            record["scope"] = scope
        packet["permissions"]["deliver"] = {
            **packet["permissions"]["submit"], "action": "deliver",
        }
        return lead

    def test_private_direct_route_needs_no_social_publication(self):
        lead = self.make_private()
        packet = lead["packet"]
        result = qualify(packet, NOW)
        self.assertEqual(result["status"], "evidence_complete")
        self.assertEqual(result["capabilities"]["deliver"], "automated")
        for action in ("publish", "submit", "read_metrics"):
            self.assertEqual(result["capabilities"][action], "disabled")
        report = rank_campaigns([lead], now=NOW)
        self.assertEqual(len(report["ranked"]), 1)
        self.assertFalse(report["live_enabled"])
        self.assertFalse(qualify(packet, NOW)["live_enabled"])

    def test_private_route_requires_explicit_current_automated_delivery(self):
        for changes in ({"mode": "manual"}, {"expires_at": NOW.isoformat()},
                        {"scope": {"platform": "youtube"}}, {"action": "publish"}):
            with self.subTest(changes=changes):
                lead = self.make_private()
                lead["packet"]["permissions"]["deliver"].update(changes)
                self.assertFalse(rank_campaigns([lead], now=NOW)["ranked"])
        lead = self.make_private()
        del lead["packet"]["permissions"]["deliver"]
        self.assertFalse(rank_campaigns([lead], now=NOW)["ranked"])

    def test_private_route_cannot_qualify_as_marketplace(self):
        lead = self.make_private()
        packet = lead["packet"]
        packet["marketplace"] = "content_rewards"
        result = qualify(packet, NOW)
        self.assertIn("private_delivery_requires_direct_agreement", result["blockers"])
        self.assertFalse(rank_campaigns([lead], now=NOW, route="content_rewards")["ranked"])

    def test_blank_template_does_not_qualify(self):
        result = rank_campaigns([{"packet": direct_pilot_template("lead")}], now=NOW)
        self.assertEqual(result["status"], "no_eligible_work")
        self.assertIn("direct_agreement", result["blocked"][0]["reasons"])
