"""Deterministic financial model. Agents argue; this file does all the math.

Every number shown in the boardroom comes from `evaluate()`, so the
debate can never drift from the actual figures.

An option is a mix of five levers:
  engineers         engineers to hire (cost per month, growth lift after a ramp)
  marketing_budget  $ spent over the marketing period (CAC rises with spend)
  price_change      fraction, e.g. 0.15 = +15% price (some customers leave,
                    churn rises a little; a cut does the opposite)
  cost_cut          $ per month of operating costs removed (one-off severance,
                    and organic growth slows in proportion to the cut)
  fundraise         $ of new cash in month 1 (counted at a cost of capital in
                    net value; it extends runway but is not free)
"""
from copy import deepcopy

HORIZON = 36  # months simulated
INT_KEYS = {"eng_ramp_months", "marketing_months", "min_stress_runway"}

LEVERS = ("engineers", "marketing_budget", "price_change", "cost_cut", "fundraise")

# Defaults for assumptions that older scenario files don't set.
DEFAULT_ASSUMPTIONS = {
    "price_churn_sensitivity": 0.5,   # +10% price loses 5% of customers once
    "price_churn_monthly": 0.02,      # +10% price adds 0.2 pts of monthly churn
    "cost_cut_growth_drag": 1.5,      # cutting 20% of opex slows organic growth by 30% (relative)
    "severance_months": 3,            # one-off cost of a cut, in months of the cut
    "capital_cost": 0.15,             # cost of raised money, counted in net value
}


def lever(option, key):
    return float(option.get(key) or 0)


def simulate(company, a, option, mrr_shock=0.0):
    """Month-by-month cash and MRR simulation for one option."""
    gm = company["gross_margin"]
    engineers = lever(option, "engineers")
    price = lever(option, "price_change")
    cut = min(lever(option, "cost_cut"), company["monthly_opex"] * 0.6)
    raised = lever(option, "fundraise")
    mkt_months = max(1, int(a["marketing_months"]))
    mkt_monthly = lever(option, "marketing_budget") / mkt_months

    # Price: revenue per customer moves by `price`, and a share of customers
    # leaves (price up) or arrives (price down).
    mrr = company["mrr"] * (1 + price) * (1 - a["price_churn_sensitivity"] * price)
    mrr *= (1 - mrr_shock)
    churn = max(0.0, company["churn"] + a["price_churn_monthly"] * price)
    organic = company["organic_growth"] * (1 - a["cost_cut_growth_drag"] * cut / company["monthly_opex"])
    arpa = company["arpa"] * (1 + price)
    cash = company["cash"] + raised

    rows = []
    runway = None
    for m in range(1, HORIZON + 1):
        growth = organic - churn
        if engineers and m > a["eng_ramp_months"]:
            growth += engineers * a["eng_growth_lift"]
        spend = mkt_monthly if m <= mkt_months else 0.0
        # CAC rises as monthly spend saturates the channel (diminishing returns).
        eff_cac = a["cac"] * (1 + spend / a["cac_saturation_spend"]) if spend else a["cac"]
        new_mrr = (spend / eff_cac) * arpa if eff_cac else 0.0
        mrr = mrr * (1 + growth) + new_mrr

        severance = cut * a["severance_months"] if m == 1 else 0.0
        extra_cost = engineers * a["eng_monthly_cost"] + spend + severance - cut
        cash_flow = mrr * gm - company["monthly_opex"] - extra_cost
        cash += cash_flow
        rows.append({"month": m, "mrr": mrr, "cash": cash, "extra_cost": extra_cost, "gp": mrr * gm})
        if runway is None and cash < 0:
            runway = m - 1
    return rows, (runway if runway is not None else HORIZON)


BASELINE = {"id": "0", "label": "Do nothing"}


def evaluate(data, overrides=None):
    """Return metrics for every option plus the baseline and the guardrail verdict."""
    company = data["company"]
    a = {**DEFAULT_ASSUMPTIONS, **deepcopy(data["assumptions"])}
    if overrides:
        for k, v in overrides.items():
            if k in a and v is not None:
                a[k] = int(round(float(v))) if k in INT_KEYS else float(v)

    base_rows, base_runway = simulate(company, a, BASELINE)
    _, base_stress = simulate(company, a, BASELINE, a["stress_mrr_shock"])
    gm = company["gross_margin"]

    results = []
    for opt in data["options"]:
        rows, runway = simulate(company, a, opt)
        _, stress_runway = simulate(company, a, opt, a["stress_mrr_shock"])

        capital_cost = lever(opt, "fundraise") * a["capital_cost"]
        cum_cost = capital_cost  # net cost: new spend + severance + cost of capital - savings
        cum_gp = 0.0
        payback = None
        for r, b in zip(rows[:24], base_rows[:24]):
            cum_cost += r["extra_cost"]
            cum_gp += r["gp"] - b["gp"]
            if payback is None and cum_cost > 0 and cum_gp >= cum_cost:
                payback = r["month"]
        if payback is None and cum_cost <= 0:
            payback = 0  # saves money overall: nothing to pay back

        inc_mrr_12 = rows[11]["mrr"] - base_rows[11]["mrr"]
        inc_mrr_24 = rows[23]["mrr"] - base_rows[23]["mrr"]
        # Net value = 24-month incremental gross profit minus net cost, plus the
        # next 12 months of gross profit from the revenue change it caused.
        net_value = cum_gp - cum_cost + 12 * inc_mrr_24 * gm
        results.append({
            "id": opt["id"],
            "label": opt["label"],
            **{k: lever(opt, k) for k in LEVERS},
            "cost_24": round(cum_cost),
            "inc_mrr_12": round(inc_mrr_12),
            "inc_mrr_24": round(inc_mrr_24),
            "mrr_24": round(rows[23]["mrr"]),
            "net_value": round(net_value),
            "roi_24": round(net_value / cum_cost, 3) if cum_cost > 0 else None,
            "payback": payback,
            "runway": runway,
            "stress_runway": stress_runway,
            "passes_guardrail": stress_runway >= a["min_stress_runway"],
            "cash_curve": [round(r["cash"]) for r in rows[:24]],
        })

    eligible = [r for r in results if r["passes_guardrail"]]
    # Decision rule: among options that survive the stress test, pick the
    # highest net value. Ties broken by incremental MRR.
    winner = max(eligible, key=lambda r: (r["net_value"], r["inc_mrr_24"])) if eligible else None

    return {
        "assumptions": a,
        "baseline": {"runway": base_runway, "stress_runway": base_stress,
                     "mrr_24": round(base_rows[23]["mrr"]),
                     "cash_curve": [round(r["cash"]) for r in base_rows[:24]]},
        "options": results,
        "winner": winner["id"] if winner else None,
    }
