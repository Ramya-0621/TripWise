"""
recommender.py  -  THE RECOMMENDATION ENGINE
============================================
Workflow (each step is a function below):

  1. validate_request()   check and clean the user's input
  2. load knowledge       KnowledgeBase (JSON files)
  3. filter_destinations  CONSTRAINT-BASED PRUNING of whole destinations
  4. bfs_search           BFS over  destination -> transport -> accommodation -> activities
                          with early pruning (budget, travel-time, capacity)
  5. score each finished itinerary with the weighted HEURISTIC
  6. keep the best itinerary per destination (respecting transport preference)
  7. top_k()              PRIORITY-BASED RANKING, return the best 3-5
  8. explain              reasons + rules fired for each result
  9. if nothing fits      relax constraints step by step (rule R11) or explain why

All prices are illustrative estimates; see rules.py for the cost model.
"""
from dataclasses import dataclass
from typing import Optional, Tuple

import rules as R
from knowledge_base import get_kb
from search_algorithms import filter_destinations, bfs_search, top_k

MAX_RESULTS = 5


# ============================================================== validation
class ValidationError(Exception):
    """Bad user input. `details` is a list of human-readable problems."""

    def __init__(self, details):
        self.details = details
        super().__init__("; ".join(details))


def _to_number(value):
    """Accept numbers or numeric strings, never booleans."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "").strip())
        except ValueError:
            return None
    return None


def validate_request(payload, kb):
    """Return a clean request dict or raise ValidationError listing every problem."""
    if not isinstance(payload, dict):
        raise ValidationError(["Request body must be a JSON object."])

    errors = []
    req = {}

    # Starting city (must be known because distances come from coordinates)
    city_name = payload.get("starting_city")
    if not isinstance(city_name, str) or not city_name.strip():
        errors.append("starting_city is required.")
    else:
        origin = kb.find_city(city_name)
        if origin is None:
            errors.append(f"Unknown starting city '{city_name.strip()}'. Supported cities: {', '.join(kb.city_names())}.")
        else:
            req["origin"] = origin
            req["starting_city"] = origin["name"]

    # Budget
    budget = _to_number(payload.get("budget"))
    if budget is None:
        errors.append("budget is required and must be a number (in rupees).")
    elif not 1000 <= budget <= 10_000_000:
        errors.append("budget must be between 1,000 and 10,000,000 rupees.")
    else:
        req["budget"] = int(budget)

    # Duration
    days = _to_number(payload.get("days"))
    if days is None or days != int(days):
        errors.append("days is required and must be a whole number.")
    elif not 1 <= days <= 30:
        errors.append("days must be between 1 and 30.")
    else:
        req["days"] = int(days)

    # Travelers
    travelers = _to_number(payload.get("travelers", 1))
    if travelers is None or travelers != int(travelers):
        errors.append("travelers must be a whole number.")
    elif not 1 <= travelers <= 20:
        errors.append("travelers must be between 1 and 20.")
    else:
        req["travelers"] = int(travelers)

    # Category / transport / accommodation (choice fields)
    category = payload.get("category", "any") or "any"
    if category != "any" and category not in kb.category_ids:
        errors.append(f"category must be 'any' or one of: {', '.join(kb.category_ids)}.")
    req["category"] = category

    transport = payload.get("transport", "auto") or "auto"
    if transport != "auto" and transport not in kb.transport_modes:
        errors.append(f"transport must be 'auto' or one of: {', '.join(kb.transport_modes)}.")
    req["transport"] = transport

    accommodation = payload.get("accommodation", "any") or "any"
    if accommodation != "any" and accommodation not in kb.tier_ids:
        errors.append(f"accommodation must be 'any' or one of: {', '.join(kb.tier_ids)}.")
    req["accommodation"] = accommodation

    # Interests
    interests = payload.get("interests", [])
    if interests is None:
        interests = []
    if not isinstance(interests, list) or not all(isinstance(i, str) for i in interests):
        errors.append("interests must be a list of interest ids.")
    else:
        unknown = [i for i in interests if i not in kb.interest_ids]
        if unknown:
            errors.append(f"Unknown interests: {', '.join(unknown)}.")
        req["interests"] = list(dict.fromkeys(interests))  # remove duplicates, keep order

    # Optional heuristic weights
    weights = payload.get("weights")
    if weights is not None:
        if not isinstance(weights, dict) or any(
                k not in R.DEFAULT_WEIGHTS or _to_number(v) is None or _to_number(v) < 0 for k, v in weights.items()):
            errors.append(f"weights must map {', '.join(R.DEFAULT_WEIGHTS)} to non-negative numbers.")
        else:
            req["weights"] = {k: _to_number(v) for k, v in weights.items()}
    req.setdefault("weights", None)

    if errors:
        raise ValidationError(errors)
    return req


# ============================================================ search state
@dataclass(frozen=True)
class TripState:
    """
    One node of the BFS state space. `stage` tells how far we are:
      start -> destination -> transport -> accommodation -> activities -> complete
    """
    stage: str
    destination: Optional[dict] = None
    transport: Optional[dict] = None
    tier: Optional[str] = None
    activities: Tuple[dict, ...] = ()
    next_activity: int = 0      # activities are added in index order -> no duplicate subsets
    base_cost: int = 0          # transport + stay + food + local (no activities)
    activity_cost: int = 0
    slots_used: int = 0


def _search(candidates, req, kb):
    """Run BFS over the trip-planning state space for the given destinations."""
    days, travelers, budget = req["days"], req["travelers"], req["budget"]
    tiers = kb.tier_ids if req["accommodation"] == "any" else [req["accommodation"]]
    capacity = R.slots_available(days)
    option_cache = {}

    def options_for(dest):
        if dest["id"] not in option_cache:
            opts = R.transport_options(dest, req["origin"], kb.transport_modes)
            option_cache[dest["id"]] = R.order_transport(opts, req["transport"])  # R8
        return option_cache[dest["id"]]

    def cheapest_stay_cost(dest, option):
        return min(R.calculate_cost(dest, option, t, [], travelers, days)["total"] for t in tiers)

    def expand(state):
        d = state.destination
        if state.stage == "start":                       # level 0 -> 1
            return [TripState("destination", destination=dest) for dest in candidates]
        if state.stage == "destination":                 # level 1 -> 2
            return [TripState("transport", d, opt) for opt in options_for(d)]
        if state.stage == "transport":                   # level 2 -> 3
            children = []
            for tier in tiers:
                cost = R.calculate_cost(d, state.transport, tier, [], travelers, days)
                children.append(TripState("accommodation", d, state.transport, tier, base_cost=cost["total"]))
            return children
        # accommodation / activities: finish here, or add one more activity
        children = [TripState("complete", d, state.transport, state.tier, state.activities,
                              state.next_activity, state.base_cost, state.activity_cost, state.slots_used)]
        for i in range(state.next_activity, len(d["activities"])):
            act = d["activities"][i]
            children.append(TripState(
                "activities", d, state.transport, state.tier, state.activities + (act,), i + 1,
                state.base_cost, state.activity_cost + act["cost_pp"] * travelers,
                state.slots_used + act["slots"]))
        return children

    def prune(child):
        """True = discard this branch immediately."""
        if child.stage == "transport":
            if not R.rule_travel_time_ok(child.transport, days):                       # R7
                return True
            return cheapest_stay_cost(child.destination, child.transport) > budget    # R5 (lower bound)
        if child.stage == "accommodation":
            return child.base_cost > budget                                            # R5
        if child.stage == "activities":
            return (child.base_cost + child.activity_cost > budget                     # R5
                    or child.slots_used > capacity)                                    # R10
        return False

    return bfs_search(TripState("start"), expand, lambda s: s.stage == "complete", prune)


# ================================================================= scoring
def _evaluate(state, req, weights, kb):
    """Compute the cost breakdown and heuristic score for one finished itinerary."""
    dest = state.destination
    cost = R.calculate_cost(dest, state.transport, state.tier, state.activities, req["travelers"], req["days"])
    status, dur_score, dur_note = R.rule_duration_status(dest, req["days"])
    matched = R.matched_interests(dest, state.activities, req["interests"])
    components = {
        "interest": R.interest_score(dest, state.activities, req["interests"]),
        "category": R.category_score(dest, req["category"]),
        "budget_fit": R.budget_fit_score(cost["total"], req["budget"]),
        "duration": dur_score,
        "transport": R.transport_score(state.transport, req["transport"]),
    }
    score = 100 * sum(weights[k] * components[k] for k in weights)
    return {"state": state, "cost": cost, "components": components, "score": score,
            "matched": matched, "duration_note": dur_note}


def _format(rank, ev, req, weights, kb):
    """Turn an evaluated itinerary into the JSON structure sent to the browser."""
    s, cost, dest = ev["state"], ev["cost"], ev["state"].destination
    labels = {"interest": "Interest match", "category": "Category match", "budget_fit": "Budget fit",
              "duration": "Duration suitability", "transport": "Transport preference"}

    all_options = R.transport_options(dest, req["origin"], kb.transport_modes)
    alternatives = [{
        **o, "selected": o["mode"] == s.transport["mode"],
        "fare_total": o["fare_pp_round_trip"] * req["travelers"],
        "fits_time_rule": R.rule_travel_time_ok(o, req["days"]),
    } for o in all_options]

    rules_fired = ["R4 duration rule applied", "R5 total is within budget", "R7 travel time is within 40% of the trip"]
    if req["category"] != "any":
        rules_fired.append("R2 category match scored")
    if req["interests"]:
        rules_fired.append("R3 interest match scored")
    if req["transport"] != "auto":
        rules_fired.append("R8 preferred transport considered first")
    rules_fired.append(f"R9 accommodation priced at {s.tier} rates")

    remaining = req["budget"] - cost["total"]
    return {
        "rank": rank,
        "destination": kb.public_destination(dest),
        "score": round(ev["score"], 1),
        "score_breakdown": [{
            "key": k, "label": labels[k], "raw": round(ev["components"][k], 2),
            "weight": round(weights[k], 2), "points": round(100 * weights[k] * ev["components"][k], 1),
        } for k in weights],
        "transport": {
            "mode": s.transport["mode"], "label": s.transport["label"],
            "distance_km": s.transport["distance_km"], "one_way_hours": s.transport["one_way_hours"],
            "fare_per_person_round_trip": s.transport["fare_pp_round_trip"],
            "total": cost["transport"], "matches_preference": req["transport"] in ("auto", s.transport["mode"]),
            "alternatives": alternatives,
        },
        "accommodation": {
            "tier": s.tier, "rooms": cost["rooms"], "nights": cost["nights"],
            "rate_per_room_night": cost["rate_per_room_night"], "total": cost["accommodation"],
            "pricing_note": f"₹{cost['rate_per_room_night']:,} per room per night; 2 travelers share a room.",
        },
        "activities": [{"name": a["name"], "cost_pp": a["cost_pp"], "total": a["cost_pp"] * req["travelers"],
                        "slots": a["slots"], "tags": a["tags"]} for a in s.activities],
        "budget": {
            "transport": cost["transport"], "accommodation": cost["accommodation"], "food": cost["food"],
            "local_transport": cost["local_transport"], "activities": cost["activities"],
            "total": cost["total"], "budget": req["budget"], "remaining": remaining,
            "percent_used": round(100 * cost["total"] / req["budget"], 1),
        },
        "reasons": R.build_reasons(dest, req, s.transport, s.tier, s.activities, cost,
                                   ev["components"], ev["matched"], ev["duration_note"], kb.category_labels),
        "rules_fired": rules_fired,
    }


def _rank_key(ev):
    """Higher is better. Ties (scores equal to 1 decimal) prefer more matched interests,
    then a fuller activity plan, then the cheaper trip."""
    return (round(ev["score"], 1), len(ev["matched"]), len(ev["state"].activities), -ev["cost"]["total"])


def _best_per_destination(goals, req, weights, kb):
    """Evaluate every finished itinerary, keep the best one per destination (R8 filter first)."""
    groups = {}
    for state in goals:
        groups.setdefault(state.destination["id"], []).append(_evaluate(state, req, weights, kb))
    best = []
    for evals in groups.values():
        if req["transport"] != "auto":
            preferred = [e for e in evals if e["state"].transport["mode"] == req["transport"]]
            if preferred:           # respect the preference whenever it is feasible
                evals = preferred
        best.append(max(evals, key=_rank_key))
    return best


# ============================================================ no-result help
def _diagnose(req, kb):
    """Explain why nothing fit and what the user could change."""
    origin, days, travelers = req["origin"], req["days"], req["travelers"]
    tiers = kb.tier_ids if req["accommodation"] == "any" else [req["accommodation"]]
    pool = [d for d in kb.destinations if R.rule_not_too_close(origin, d)]
    suggestions = []

    ok_days = [d for d in pool if R.rule_duration_status(d, days)[0] == "ok"]
    if not ok_days:
        shortest = min(d["days"]["min"] for d in pool)
        suggestions.append(f"Increase the trip to at least {shortest} days - every destination needs more time than {days}.")
        return suggestions

    def cheapest(dest):
        costs = []
        for opt in R.transport_options(dest, origin, kb.transport_modes):
            if R.rule_travel_time_ok(opt, days):
                for t in tiers:
                    costs.append(R.calculate_cost(dest, opt, t, [], travelers, days)["total"])
        return min(costs) if costs else None

    priced = [(cheapest(d), d) for d in ok_days]
    priced = [(c, d) for c, d in priced if c is not None]
    if not priced:
        suggestions.append("Travel time is too long for this trip length. Add more days or choose a closer start city.")
        return suggestions

    cost, dest = min(priced, key=lambda p: p[0])
    suggestions.append(f"Increase the budget to at least ₹{cost:,}: the cheapest option we know is {dest['name']} "
                       f"at about ₹{cost:,} for {travelers} traveler(s) and {days} day(s).")
    if req["category"] != "any":
        in_cat = [(c, d) for c, d in priced if R.rule_category_allowed(d, req["category"])]
        if in_cat:
            c2, d2 = min(in_cat, key=lambda p: p[0])
            suggestions.append(f"For your chosen category the cheapest is {d2['name']} at about ₹{c2:,}.")
    if req["accommodation"] == "luxury":
        suggestions.append("Try Standard or Budget accommodation to lower the cost.")
    if travelers > 1:
        suggestions.append("Fewer travelers lowers the total (transport, food and activities are charged per person).")
    return suggestions


# ================================================================ main API
def recommend(payload, kb=None):
    """Validate -> filter -> BFS -> score -> rank -> explain. Returns a JSON-ready dict."""
    kb = kb or get_kb()
    req = validate_request(payload, kb)
    weights = R.normalise_weights(req["weights"])
    origin, days = req["origin"], req["days"]

    # R11: ladder of progressively relaxed constraints. Duration and budget are never relaxed.
    cat = req["category"]
    ladder = [(None, cat, True)]
    if req["interests"]:
        ladder.append(("your interests", cat, False))
    if cat != "any":
        if req["interests"]:
            ladder.append(("your preferred category", "any", True))
        ladder.append(("your preferred category" + (" and interests" if req["interests"] else ""), "any", False))

    total_stats = {"destinations_in_knowledge_base": len(kb.destinations), "attempts": 0}
    for relaxed_what, category, use_interests in ladder:
        constraints = [
            ("too close to the start city", lambda d: R.rule_not_too_close(origin, d)),                  # R1
            ("category", lambda d, c=category: R.rule_category_allowed(d, c)),                            # hard
            ("interests", lambda d, u=use_interests: (not u) or R.rule_has_interest_overlap(d, req["interests"])),
            ("trip too short", lambda d: R.rule_duration_status(d, days)[0] == "ok"),                     # R4
        ]
        candidates, rejected = filter_destinations(kb.destinations, constraints)
        total_stats["attempts"] += 1
        if not candidates:
            continue

        goals, stats = _search(candidates, req, kb)
        if not goals:
            continue

        evaluated = _best_per_destination(goals, req, weights, kb)
        ranked = top_k(evaluated, MAX_RESULTS, key=_rank_key)
        itineraries = [_format(i + 1, ev, req, weights, kb) for i, ev in enumerate(ranked)]

        notes = []
        message = f"Found {len(itineraries)} trip{'s' if len(itineraries) != 1 else ''} that fit your budget."
        if relaxed_what:
            notes.append(f"No destination fit all of your preferences within your budget and trip length, "
                         f"so we relaxed {relaxed_what}. Results below are the closest alternatives.")
            message = "No exact match found - showing the closest alternatives."
        return {
            "query": {k: v for k, v in req.items() if k not in ("origin", "weights")},
            "count": len(itineraries), "message": message, "notes": notes,
            "relaxed": relaxed_what, "suggestions": [], "itineraries": itineraries,
            "weights_used": {k: round(v, 3) for k, v in weights.items()},
            "stats": {**total_stats, "destinations_after_filtering": len(candidates),
                      "filtered_out": {k: len(v) for k, v in rejected.items()},
                      "bfs_nodes_expanded": stats["expanded"], "bfs_nodes_generated": stats["generated"],
                      "bfs_nodes_pruned": stats["pruned"], "pruned_by_stage": stats["pruned_by_stage"],
                      "itineraries_evaluated": len(goals)},
            "disclaimer": R.DISCLAIMER,
        }

    return {
        "query": {k: v for k, v in req.items() if k not in ("origin", "weights")},
        "count": 0, "itineraries": [], "relaxed": None, "notes": [],
        "message": "No trip fits these requirements.",
        "suggestions": _diagnose(req, kb),
        "weights_used": {k: round(v, 3) for k, v in weights.items()},
        "stats": {**total_stats},
        "disclaimer": R.DISCLAIMER,
    }
