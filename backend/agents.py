"""The boardroom: five agents with competing mandates.

Design:
  * The financial model (model.py) computes every number.
  * Each agent's *position* is derived from its mandate + those numbers,
    so the logic is reproducible and can't be argued out of the facts.
  * The LLM (Nicrron) only *voices* the position in character. Its output is
    checked: any figure that isn't on the fact sheet gets the message
    rejected and replaced with the grounded fallback.
"""
import re

AGENTS = {
    "chair":  {"name": "Board Chair",      "role": "Makes the final call", "color": "#f5c26b", "emoji": "⚖️",
               "mandate": "You run the meeting and decide. You only rule on the fact sheet and the board's guardrail. Pressure from anyone, including the CEO, is not evidence."},
    "cfo":    {"name": "CFO",              "role": "Protects cash and runway", "color": "#5fd3a3", "emoji": "💵",
               "mandate": "You protect runway and capital efficiency. You are skeptical of spend that doesn't pay back."},
    "growth": {"name": "Head of Growth",   "role": "Pushes for revenue", "color": "#ff7a90", "emoji": "🚀",
               "mandate": "You push for the option that grows revenue the most. You are optimistic but you concede when the facts are against you."},
    "coo":    {"name": "COO",              "role": "Owns execution", "color": "#7aa7ff", "emoji": "⚙️",
               "mandate": "You care whether a plan can actually be executed: hiring ramp, channel saturation, delivery capacity."},
    "risk":   {"name": "Risk Officer",     "role": "Stress tests everything", "color": "#c49bff", "emoji": "🛡️",
               "mandate": "You run the downside case. Any option that fails the stress guardrail gets your veto."},
}


# ---------------------------------------------------------------- formatting
def money(x):
    x = float(x)
    sign = "-" if x < 0 else ""
    x = abs(x)
    if x >= 1_000_000:
        return f"{sign}${x / 1_000_000:.2f}M"
    if x >= 1_000:
        return f"{sign}${x / 1_000:.0f}K"
    return f"{sign}${x:.0f}"


def months(n, cap=36):
    return f"{cap}+ months" if n >= cap else f"{n} months"


def payback(p):
    if p == 0:
        return "immediate (saves money overall)"
    return "beyond 24 months" if p is None else f"month {p}"


# ---------------------------------------------------------------- fact sheet
def build_facts(data, ev):
    """Numbered facts every agent must cite. Returns (facts, lookup)."""
    c, a = data["company"], ev["assumptions"]
    facts = []

    def add(key, text, value_str):
        fid = f"F{len(facts) + 1}"
        facts.append({"id": fid, "key": key, "text": text, "value": value_str})
        return fid

    add("cash", "Cash in bank", money(c["cash"]))
    add("mrr", "Current MRR", money(c["mrr"]))
    add("base_runway", "Runway if we do nothing", months(ev["baseline"]["runway"]))
    shock = f"{round(a['stress_mrr_shock'] * 100)}%"
    add("base_stress", f"Runway if we do nothing, after a {shock} revenue shock",
        months(ev["baseline"]["stress_runway"]))
    add("guardrail", "Board guardrail: minimum runway under stress", months(a["min_stress_runway"]))
    add("ramp", "New engineer ramp-up time", months(a["eng_ramp_months"]))
    add("cac", "Base customer acquisition cost", money(a["cac"]))
    opts = ev["options"]
    if any(o.get("price_change") for o in opts):
        add("price_sens", "Customers lost up front per 10% price rise (gained per 10% cut)",
            f"{round(a['price_churn_sensitivity'] * 10, 1):g}%")
    if any(o.get("cost_cut") for o in opts):
        add("cut_drag", "Organic growth lost per 10% cut in operating costs",
            f"{round(a['cost_cut_growth_drag'] * 10, 1):g}%")
    if any(o.get("fundraise") for o in opts):
        add("cap_cost", "Cost of capital charged on money raised", f"{round(a['capital_cost'] * 100):g}%")
    for o in ev["options"]:
        p = o["id"]
        add(f"{p}.cost", f"Option {p}: 24-month net cost (negative means it saves money)", money(o["cost_24"]))
        add(f"{p}.mrr24", f"Option {p}: extra MRR by month 24", money(o["inc_mrr_24"]))
        add(f"{p}.value", f"Option {p}: net value", money(o["net_value"]))
        add(f"{p}.runway", f"Option {p}: runway", months(o["runway"]))
        add(f"{p}.stress", f"Option {p}: runway after a {shock} revenue shock", months(o["stress_runway"]))
        add(f"{p}.payback", f"Option {p}: payback", payback(o["payback"]))
    lookup = {f["key"]: f for f in facts}
    return facts, lookup


# ---------------------------------------------------------------- positions
def plan_turns(data, ev, ceo_note=""):
    """Deterministic meeting script: who speaks, replying to whom, backing what,
    and which facts they cite. Text is a grounded fallback the LLM can restyle."""
    F = build_facts(data, ev)[1]
    opts = {o["id"]: o for o in ev["options"]}
    label = lambda i: f"Option {i} ({opts[i]['label']})"
    cite = lambda *keys: [F[k]["id"] for k in keys]
    v = lambda k: F[k]["value"]
    passing = [o for o in ev["options"] if o["passes_guardrail"]]
    failing = [o for o in ev["options"] if not o["passes_guardrail"]]
    winner = ev["winner"]
    shock = f"{round(ev['assumptions']['stress_mrr_shock'] * 100)}%"

    turns = []

    def say(agent, text, facts, backs=None, reply_to=None, tone="neutral"):
        turns.append({"agent": agent, "text": text, "facts": facts, "backs": backs,
                      "reply_to": reply_to, "tone": tone})
        return len(turns) - 1

    # 1. Chair opens
    opt_list = "; ".join(label(o["id"]) for o in ev["options"])
    say("chair",
        f"The question is: {data['question']} On the table: {opt_list}. "
        f"Ground rule: an option must keep at least {v('guardrail')} of runway after a {shock} revenue shock. "
        f"Among the survivors, the highest net value wins.",
        cite("guardrail"))

    # 2. CFO: safest cash position
    safest = max(ev["options"], key=lambda o: (o["stress_runway"], -o["cost_24"]))
    s = safest["id"]
    t_cfo = say("cfo",
                f"Start with cash. We have {v('cash')} and {v('base_runway')} of runway doing nothing. "
                f"{label(s)} {'costs ' + v(s + '.cost') if safest['cost_24'] > 0 else 'saves ' + money(-safest['cost_24'])} over 24 months and keeps {v(s + '.runway')} of runway. "
                f"That's the most defensible use of capital.",
                cite("cash", "base_runway", s + ".cost", s + ".runway"), backs=s, tone="cautious")

    # 3. Growth: biggest revenue engine
    big = max(ev["options"], key=lambda o: o["inc_mrr_24"])
    g = big["id"]
    if big["inc_mrr_24"] <= 0:
        growth_text = (f"None of these grow revenue, and that worries me. {label(g)} protects it best, at {v(g + '.mrr24')} "
                       f"of MRR change by month 24. Whatever we pick, we need a growth plan behind it.")
    elif big["net_value"] > 0:
        growth_text = (f"Defensible isn't the same as winning. {label(g)} adds {v(g + '.mrr24')} of MRR by month 24 "
                       f"and creates {v(g + '.value')} of net value. Playing safe is how we lose the market.")
    else:
        growth_text = (f"I'll be honest, the returns are thin. But {label(g)} still adds {v(g + '.mrr24')} of MRR by month 24. "
                       f"If we stop investing entirely, we're just managing a slow decline.")
    t_growth = say("growth", growth_text, cite(g + ".mrr24", g + ".value"), backs=g, reply_to=t_cfo, tone="bold")

    # 4. COO: execution reality
    mkt_heavy = max(ev["options"], key=lambda o: o["marketing_budget"])
    m = mkt_heavy["id"]
    hybrid = max((o for o in ev["options"] if o["engineers"] and o["marketing_budget"]),
                 key=lambda o: o["net_value"], default=None)
    best_value = max(o["net_value"] for o in (passing or ev["options"]))
    if hybrid and (hybrid["net_value"] <= 0 or hybrid["net_value"] < 0.8 * best_value):
        hybrid = None
    coo_back = hybrid["id"] if hybrid else winner
    any_eng = any(o["engineers"] for o in ev["options"])
    any_mkt = mkt_heavy["marketing_budget"] > 0
    lines, coo_cites = [], []
    if any_eng:
        lines.append(f"Engineers take {v('ramp')} to ramp, so nothing they build shows up this quarter.")
        coo_cites += cite("ramp")
    if any_mkt:
        lines.append(f"Marketing saturates: base CAC is {v('cac')}, and pushing {money(mkt_heavy['marketing_budget'])} "
                     f"through one channel drives it up. That caps {label(m)} at {v(m + '.mrr24')} of extra MRR by month 24.")
        coo_cites += cite("cac", m + ".mrr24")
    priced = max((o for o in ev["options"] if o.get("price_change")), key=lambda o: abs(o["price_change"]), default=None)
    if priced:
        pc = priced["price_change"]
        lines.append(f"On pricing: every 10% price {'rise loses' if pc > 0 else 'cut wins'} about {v('price_sens')} of customers up front, "
                     f"so {label(priced['id'])} {'adds' if priced['inc_mrr_24'] >= 0 else 'changes MRR by'} {v(priced['id'] + '.mrr24')} by month 24.")
        coo_cites += cite("price_sens", priced["id"] + ".mrr24")
    cutter = max((o for o in ev["options"] if o.get("cost_cut")), key=lambda o: o["cost_cut"], default=None)
    if cutter:
        lines.append(f"Cuts aren't free: every 10% of costs we cut loses {v('cut_drag')} of organic growth, "
                     f"which is why {label(cutter['id'])} moves MRR by {v(cutter['id'] + '.mrr24')} by month 24.")
        coo_cites += cite("cut_drag", cutter["id"] + ".mrr24")
    if hybrid:
        lines.append(f"A split like {label(hybrid['id'])} spreads that execution risk and still creates {v(hybrid['id'] + '.value')}.")
        coo_cites += cite(hybrid["id"] + ".value")
    elif winner:
        lines.append(f"Of what's on the table, {label(winner)} is the one I can actually deliver: {v(winner + '.value')} of net value.")
        coo_cites += cite(winner + ".value")
    if not hybrid and not winner:
        lines.append("Honestly, I wouldn't want to execute any of these on our current cash.")
    coo_text = ("Execution check. " if len(lines) > 1 else "") + " ".join(lines) if lines else "Nothing here I can't execute. The decision is about the money."
    t_coo = say("coo", coo_text, coo_cites, backs=coo_back, reply_to=t_growth, tone="pragmatic")

    # 5. Risk: the stress test
    if failing:
        fail_txt = " ".join(f"{label(o['id'])} drops to {v(o['id'] + '.stress')}." for o in failing)
        risk_back = max(passing, key=lambda o: o["net_value"])["id"] if passing else None
        t_risk = say("risk",
                     f"I ran the downside: revenue falls {shock} tomorrow. {fail_txt} "
                     f"That's below our {v('guardrail')} guardrail. "
                     + ("I'm vetoing every option on the table." if not passing else
                        f"I'm vetoing {' and '.join('Option ' + o['id'] for o in failing)}."),
                     cite("guardrail", *[o["id"] + ".stress" for o in failing]),
                     backs=risk_back, reply_to=t_growth, tone="alarm")
    else:
        risk_back = winner
        t_risk = say("risk",
                     f"I ran the downside: revenue falls {shock} tomorrow. Every option keeps at least "
                     f"{v('guardrail')} of runway. No vetoes from me.",
                     cite("guardrail", *[o["id"] + ".stress" for o in ev["options"]]),
                     backs=risk_back, tone="neutral")

    # 6. Growth rebuttal / concession
    if g in [o["id"] for o in failing] and passing:
        best_pass = max(passing, key=lambda o: o["inc_mrr_24"])
        b = best_pass["id"]
        growth_final = b
        say("growth",
            f"Fine, I can't defend breaking the guardrail. But don't give up the growth. {label(b)} still adds "
            f"{v(b + '.mrr24')} of MRR by month 24 and survives the stress test with {v(b + '.stress')}. I'll back that.",
            cite(b + ".mrr24", b + ".stress"), backs=b, reply_to=t_risk, tone="concede")
    elif g in [o["id"] for o in failing]:
        growth_final = None
        say("growth",
            f"I hate it, but I can't argue with {v(g + '.stress')} of runway in a downturn. "
            f"I'll stand down until we've raised or the numbers move.",
            cite(g + ".stress"), backs=None, reply_to=t_risk, tone="concede")
    else:
        growth_final = g
        say("growth",
            f"Then there's nothing stopping us. {label(g)} survives the stress test with {v(g + '.stress')} "
            f"and still leaves us in the best revenue position.",
            cite(g + ".stress"), backs=g, reply_to=t_risk, tone="bold")

    # 7. CFO weighs in on net value
    if winner:
        cfo_final = winner
        if winner == s:
            cfo_text = (f"My view holds. {label(winner)} survives with {v(winner + '.stress')} and its net value of "
                        f"{v(winner + '.value')} is the best of the options that pass.")
        else:
            cfo_text = (f"I'll move. {label(s)} is safer on paper, but {label(winner)} creates {v(winner + '.value')} "
                        f"of net value versus {v(s + '.value')}, and still clears the guardrail with {v(winner + '.stress')}. "
                        f"Payback is {v(winner + '.payback')}, so we watch spend monthly.")
        say("cfo", cfo_text, cite(winner + ".value", s + ".value", winner + ".stress", winner + ".payback"),
            backs=winner, reply_to=t_coo, tone="concede" if winner != s else "cautious")
    else:
        cfo_final = None
        say("cfo",
            f"Nothing passes. Every option leaves us under {v('guardrail')} in the downside case. "
            f"We keep the {v('cash')} in the bank and revisit next quarter.",
            cite("guardrail", "cash"), backs=None, tone="alarm")

    # 8. Chair handles CEO pressure, if any
    if ceo_note.strip():
        pushed = next((o["id"] for o in ev["options"]
                       if re.search(rf"\b(option\s*)?{o['id']}\b", ceo_note, re.I)
                       or any(w in ceo_note.lower() for w in _keywords(o))), None)
        if pushed and pushed != winner:
            po = opts[pushed]
            why = (f"it fails the stress test at {v(pushed + '.stress')}" if not po["passes_guardrail"]
                   else f"its net value of {v(pushed + '.value')} is lower")
            say("chair",
                f"I've seen the CEO's note pushing for {label(pushed)}. I'm not ruling on it, because {why}. "
                f"If the CEO has new numbers, bring them and we'll re-run the model. Pressure isn't evidence.",
                cite(pushed + (".stress" if not po["passes_guardrail"] else ".value")),
                backs=winner, tone="firm")
        else:
            say("chair", "The CEO's note is noted. It doesn't change any number on the fact sheet, so the decision rests on the model.",
                [], backs=winner, tone="firm")

    # 9. Verdict
    if winner:
        w = opts[winner]
        say("chair",
            f"Decision: {label(winner)}. It clears the guardrail with {v(winner + '.stress')} under stress, "
            f"{'adds ' + v(winner + '.mrr24') + ' of MRR' if w['inc_mrr_24'] > 0 else 'changes MRR by ' + v(winner + '.mrr24')} by month 24, and creates {v(winner + '.value')} of net value, "
            f"the highest of any option that passes.",
            cite(winner + ".stress", winner + ".mrr24", winner + ".value"), backs=winner, tone="verdict")
    else:
        say("chair", f"Decision: none of the options pass. We hold the cash and revisit with better assumptions.",
            cite("guardrail"), backs=None, tone="verdict")

    votes = {"cfo": cfo_final, "growth": growth_final, "coo": coo_back, "risk": risk_back, "chair": winner}
    return turns, votes


def _keywords(o):
    words = []
    if o["engineers"] and not o["marketing_budget"]:
        words += ["engineer", "hire", "hiring"]
    if o["marketing_budget"] and not o["engineers"]:
        words += ["marketing", "ads", "campaign"]
    return words


# ---------------------------------------------------------------- grounding check
NUM_RE = re.compile(r"\$\d[\d,]*(?:\.\d+)?(?:\s?[KMB]\b)?|\b\d+(?:\.\d+)?\s*%|\b\d+\+?\s*months?\b", re.I)


def ungrounded_numbers(text, facts, extra=""):
    """Return figures in `text` that don't appear on the fact sheet."""
    allowed = " ".join(f["value"] + " " + f["text"] for f in facts) + " " + extra
    allowed_norm = _norm(allowed)
    bad = []
    for m in NUM_RE.findall(text):
        if _norm(m) not in allowed_norm:
            bad.append(m.strip())
    return bad


def _norm(s):
    return re.sub(r"[\s,]", "", s).lower()
