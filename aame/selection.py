"""Choose among reviewed fixed-fee campaigns using conservative cash economics."""

from fractions import Fraction

from aame.qualification import current_evidence, identity_scope, qualify


def rank_campaigns(candidates, *, now, budget_cents=0):
    """Return an advisory decision. This never reserves money or enables work."""
    if type(budget_cents) is not int or not 0 <= budget_cents <= 30_000:
        raise ValueError("invalid available budget in cents")
    if not isinstance(candidates, list) or len(candidates) > 1_000:
        raise ValueError("expected a list of at most 1,000 candidates")
    ranked, blocked = [], []
    seen = set()
    for candidate in candidates:
        if not isinstance(candidate, dict) or not isinstance(candidate.get("packet"), dict):
            raise ValueError("each candidate requires an evidence packet")
        packet = candidate["packet"]
        scope = identity_scope(packet)
        decision = qualify(packet, now)
        entry = {"campaign": scope}
        if decision["blockers"]:
            blocked.append({**entry, "reasons": decision["blockers"]})
            continue
        key = tuple(scope.items())
        if key in seen:
            raise ValueError("duplicate qualified campaign scope")
        seen.add(key)
        if packet["platform"] != "youtube" or packet.get("marketplace") != "content_rewards":
            blocked.append({**entry, "reasons": ["unsupported_route"]})
            continue

        economics = candidate.get("economics")
        if not current_evidence(economics, now) or economics.get("scope") != scope:
            blocked.append({**entry, "reasons": ["missing_current_economics"]})
            continue
        cost = economics.get("max_cost_cents")
        odds = economics.get("minimum_collection_probability_bps")
        if (
            type(cost) is not int or cost < 0 or type(odds) is not int
            or not 0 <= odds <= 10_000
        ):
            blocked.append({**entry, "reasons": ["invalid_economics"]})
            continue
        if cost > budget_cents:
            blocked.append({**entry, "reasons": ["outside_budget"]})
            continue
        terms = packet["fixed_payment"]
        if economics.get("payment_terms") != terms:
            blocked.append({**entry, "reasons": ["economics_terms_mismatch"]})
            continue
        payout = terms["fee_usd_cents"] - terms["max_deductions_usd_cents"]
        expected_net = Fraction(payout * odds, 10_000) - cost
        if expected_net <= 0:
            blocked.append({**entry, "reasons": ["nonpositive_expected_margin"]})
            continue
        days = terms["max_clearing_days"]
        entry.update(
            max_cost_cents=cost,
            minimum_views=terms["minimum_views"],
            max_clearing_days=days,
            estimated_net_cents_floor=expected_net // 1,
            manual_actions=[
                action for action, mode in decision["capabilities"].items() if mode == "manual"
            ],
        )
        ranked.append((expected_net / max(days, 1), expected_net, entry))

    ranked.sort(key=lambda row: (
        -row[0], -row[1], row[2]["max_clearing_days"], row[2]["minimum_views"],
        tuple(str(value) for value in row[2]["campaign"].values()),
    ))
    return {
        "status": "review_required" if ranked else "no_eligible_work",
        "live_enabled": False,
        "ranked": [entry for _, _, entry in ranked],
        "blocked": blocked,
    }
