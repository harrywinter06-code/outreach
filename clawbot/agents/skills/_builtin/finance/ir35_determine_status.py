META = {
    "name": "ir35_determine_status", "builtin": True,
    "description": "Apply HMRC's CEST-style rules to a contractor engagement and return one of "
                   "'outside_ir35' (self-employed treatment), 'inside_ir35' (employed treatment), "
                   "or 'undetermined'. The three primary tests are weighed (substitution, control, "
                   "mutuality of obligation); secondary factors break ties.",
    "params": {
        "has_unfettered_substitution": "bool",
        "client_controls_how_work_done": "bool",
        "mutuality_of_obligation": "bool",
        "financial_risk": "bool",
        "part_and_parcel_of_organisation": "bool",
        "provides_own_equipment": "bool",
    },
    "returns": {"status": "str", "score": "float", "rationale": "str"},
    "cost_estimate_usd": 0.0, "timeout_s": 5.0,
}


async def run(
    ctx,
    has_unfettered_substitution: bool,
    client_controls_how_work_done: bool,
    mutuality_of_obligation: bool,
    financial_risk: bool = False,
    part_and_parcel_of_organisation: bool = False,
    provides_own_equipment: bool = False,
) -> dict:
    # An unfettered right of substitution is alone a strong indicator of being outside IR35
    # (Express & Echo Publications v Tanton). Treat it as a near-decisive primary factor.
    if has_unfettered_substitution and not client_controls_how_work_done:
        return {
            "status": "outside_ir35", "score": 0.9,
            "rationale": "Unfettered substitution + no client control over method "
                         "outweighs other factors (CEST primary test).",
        }

    score = 0.0
    reasons: list[str] = []
    if has_unfettered_substitution:
        score -= 0.3
        reasons.append("substitution right (-)")
    else:
        score += 0.2
        reasons.append("personal service (+)")
    if client_controls_how_work_done:
        score += 0.3
        reasons.append("client controls method (+)")
    else:
        score -= 0.2
        reasons.append("contractor controls method (-)")
    if mutuality_of_obligation:
        score += 0.2
        reasons.append("MOO present (+)")
    else:
        score -= 0.2
        reasons.append("no MOO (-)")
    if financial_risk:
        score -= 0.15
        reasons.append("contractor bears financial risk (-)")
    if part_and_parcel_of_organisation:
        score += 0.1
        reasons.append("integrated into client org (+)")
    if provides_own_equipment:
        score -= 0.05
        reasons.append("own equipment (-)")

    if score >= 0.25:
        status = "inside_ir35"
    elif score <= -0.25:
        status = "outside_ir35"
    else:
        status = "undetermined"
    return {
        "status": status,
        "score": round(score, 3),
        "rationale": "; ".join(reasons),
    }
