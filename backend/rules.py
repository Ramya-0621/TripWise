"""
rules.py  -  RULE-BASED REASONING + COST MODEL
==============================================
Every "IF <condition> THEN <consequence>" rule used by TripWise lives here as a
small, named function, so you can read, change or present them one by one.

RULE SUMMARY (also returned to the browser as `rules_fired`)
------------------------------------------------------------
R1  Destination too close      IF destination is < 40 km from the start city THEN reject it.
R2  Category match             IF category == preference THEN 1.0; IF only a secondary category matches THEN 0.6.
R3  Interest match             IF user interests overlap destination/activity tags THEN raise the interest score.
R4  Duration rule              IF days < minimum THEN reject; IF days > maximum THEN penalise; below ideal -> partial score.
R5  Budget rule                IF estimated total > budget THEN reject the itinerary.
R6  Transport availability     IF a mode is not available/practical for this route THEN do not offer it.
R7  Transport time rule        IF round-trip travel time > 40% of the trip THEN reject that transport mode.
R8  Transport preference       IF the user picks a mode THEN consider it first and keep it when feasible.
R9  Accommodation pricing      IF the user picks a tier THEN price the stay with that tier's rate.
R10 Capacity rule              IF chosen activities need more half-day slots than the trip has THEN reject them.
R11 Fallback rule              IF no exact match exists THEN relax interests, then category, and say so.

COST MODEL (all costs in INR, all illustrative)
-----------------------------------------------
transport      = round-trip fare per person x travelers        (+ transfer cost per person)
accommodation  = rate per ROOM per NIGHT x rooms x nights      (2 travelers share a room)
food           = food per person per day x tier multiplier x days x travelers
local transport= cost per vehicle per day x vehicles x days    (1 vehicle per 4 travelers)
activities     = sum of activity cost per person x travelers
nights = days - 1.  Each item is counted once, so nothing is double-counted.
"""
import math

# ------------------------------------------------------------------ settings
# Weights for the heuristic score. They are normalised to sum to 1, so you can
# change them freely (they can also be sent in the API request as "weights").
DEFAULT_WEIGHTS = {
    "interest": 0.35,    # how well the trip matches the traveller's interests
    "category": 0.20,    # how well it matches the preferred destination type
    "budget_fit": 0.20,  # how sensibly the budget is used
    "duration": 0.15,    # how suitable the trip length is for this destination
    "transport": 0.10,   # preferred / efficient transport mode
}

ROAD_FACTOR = 1.25               # road/rail distance ~ 1.25 x straight-line distance
MAX_TRAVEL_TIME_SHARE = 0.40     # R7: round-trip travel may use at most 40% of the trip
MIN_DISTANCE_FROM_ORIGIN_KM = 40 # R1
PERSONS_PER_ROOM = 2             # double-occupancy rooms
PERSONS_PER_VEHICLE = 4          # local cab / auto group size
SLOTS_PER_DAY = 2                # half-day activity slots per day
FOOD_TIER_MULTIPLIER = {"budget": 0.8, "standard": 1.0, "luxury": 1.5}

DISCLAIMER = ("All fares, distances, travel times and prices are illustrative estimates "
              "for planning only - not live data. Check current prices before booking.")


# ---------------------------------------------------------------- geometry
def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle (straight-line) distance between two lat/lon points in km."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def straight_distance(origin, dest):
    return haversine_km(origin["lat"], origin["lon"], dest["lat"], dest["lon"])


# --------------------------------------------------------- R1: hard filters
def rule_not_too_close(origin, dest):
    """R1: a trip to somewhere next door is not a 'trip'."""
    return straight_distance(origin, dest) >= MIN_DISTANCE_FROM_ORIGIN_KM


def rule_category_allowed(dest, category_pref):
    """Hard category constraint: primary OR secondary category must match."""
    if category_pref == "any":
        return True
    return dest["category"] == category_pref or category_pref in dest.get("secondary_categories", [])


def rule_has_interest_overlap(dest, interests):
    """Hard interest constraint: destination (or one of its activities) matches >= 1 interest."""
    if not interests:
        return True
    pool = set(dest["tags"])
    for act in dest["activities"]:
        pool.update(act["tags"])
    return bool(pool & set(interests))


def rule_duration_status(dest, days):
    """
    R4 duration rule. Returns (status, score, note).
      days <  minimum          -> reject (not enough time to enjoy it)
      minimum <= days < ideal  -> accept, score 0.7 .. 1.0 (rises with days)
      ideal  <= days <= maximum-> accept, score 1.0
      days >  maximum          -> accept but penalise: 1.0 - 0.15 per extra day (floor 0.3)
    """
    d = dest["days"]
    if days < d["min"]:
        return "reject", 0.0, f"needs at least {d['min']} days"
    if days < d["ideal"]:
        score = 0.7 + 0.3 * (days - d["min"]) / (d["ideal"] - d["min"])
        return "ok", round(score, 3), f"a bit short of the ideal {d['ideal']} days"
    if days <= d["max"]:
        return "ok", 1.0, f"fits the ideal {d['ideal']}-{d['max']} day range"
    score = max(0.3, 1.0 - 0.15 * (days - d["max"]))
    return "ok", round(score, 3), f"longer than the usual maximum of {d['max']} days"


# ------------------------------------------------------ R6/R7: transport
def transport_options(dest, origin, modes):
    """
    Build every practical transport option from origin to destination.
    R6: a mode is offered only if the destination can be reached by it and the
        distance is within the mode's sensible range.
    Fares are ESTIMATES: max(minimum fare, base + rate x km) one way, doubled for
    the round trip, plus the destination's transfer cost.
    """
    straight = straight_distance(origin, dest)
    options = []
    for mode, cfg in modes.items():
        if not dest["access"].get(mode):
            continue
        distance = straight if cfg.get("straight_line") else straight * ROAD_FACTOR
        if distance < cfg.get("min_distance_km", 0) or distance > cfg.get("max_distance_km", 1e9):
            continue
        one_way_fare = max(cfg["min_one_way_fare"], cfg["base_fare"] + cfg["rate_per_km"] * distance)
        transfer = dest["transfer_cost_pp"].get(mode, 0)
        one_way_hours = distance / cfg["speed_kmh"] + cfg["overhead_hours"]
        options.append({
            "mode": mode,
            "label": cfg["label"],
            "distance_km": round(distance),
            "one_way_hours": round(one_way_hours, 1),
            "fare_pp_round_trip": round(2 * one_way_fare + transfer),
            "transfer_pp": transfer,
        })
    return options


def rule_travel_time_ok(option, days):
    """R7: round-trip travel time must not eat more than 40% of the whole trip."""
    return 2 * option["one_way_hours"] <= MAX_TRAVEL_TIME_SHARE * days * 24


def order_transport(options, preference):
    """R8: put the preferred mode first so the search considers it first."""
    if preference == "auto":
        return list(options)
    return sorted(options, key=lambda o: 0 if o["mode"] == preference else 1)


# ------------------------------------------------------------- cost model
def rooms_needed(travelers):
    return math.ceil(travelers / PERSONS_PER_ROOM)


def vehicles_needed(travelers):
    return math.ceil(travelers / PERSONS_PER_VEHICLE)


def calculate_cost(dest, option, tier, activities, travelers, days):
    """
    Full cost breakdown for one candidate itinerary (see COST MODEL above).
    R9: accommodation uses the rate of the chosen tier.
    """
    nights = max(days - 1, 0)
    rooms = rooms_needed(travelers)
    rate = dest["accommodation_per_room_night"][tier]

    transport = option["fare_pp_round_trip"] * travelers
    accommodation = rate * rooms * nights
    food = round(dest["food_per_person_day"] * FOOD_TIER_MULTIPLIER[tier] * days * travelers)
    local = dest["local_transport_per_vehicle_day"] * vehicles_needed(travelers) * days
    acts = sum(a["cost_pp"] for a in activities) * travelers
    total = transport + accommodation + food + local + acts
    return {
        "transport": transport, "accommodation": accommodation, "food": food,
        "local_transport": local, "activities": acts, "total": total,
        "rooms": rooms, "nights": nights, "rate_per_room_night": rate,
    }


def slots_available(days):
    """R10: arrival and departure days each lose one half-day slot (minimum 1 slot)."""
    return max(1, SLOTS_PER_DAY * days - 2)


# ---------------------------------------------------- heuristic components
# Each returns a number between 0 and 1.
def category_score(dest, category_pref):
    """R2."""
    if category_pref == "any":
        return 0.5
    if dest["category"] == category_pref:
        return 1.0
    if category_pref in dest.get("secondary_categories", []):
        return 0.6
    return 0.0


def matched_interests(dest, activities, interests):
    """Interests covered by the destination's tags or by the chosen activities."""
    pool = set(dest["tags"])
    for act in activities:
        pool.update(act["tags"])
    return [i for i in interests if i in pool]


def interest_score(dest, activities, interests):
    """R3: share of the user's interests this trip covers (0.5 if none were chosen)."""
    if not interests:
        return 0.5
    return len(matched_interests(dest, activities, interests)) / len(interests)


def budget_fit_score(total, budget):
    """
    R5 + a 'sweet spot' preference. Over budget is rejected elsewhere; here we
    reward trips that use the budget sensibly instead of simply the cheapest one.
      60%-95% of budget used -> 1.0
      under 60%              -> rises 0.5 .. 1.0 (very cheap trips are not 'better')
      95%-100%               -> 0.9 (little safety margin)
    """
    ratio = total / budget
    if ratio > 1:
        return 0.0
    if ratio < 0.6:
        return 0.5 + 0.5 * (ratio / 0.6)
    if ratio <= 0.95:
        return 1.0
    return 0.9


def transport_score(option, preference):
    """
    R8: exact match with the user's choice -> 1.0, other modes -> 0.3.
    'auto': faster routes score higher (0.4 .. 1.0, falling to 0.4 at 20+ hours).
    """
    if preference == "auto":
        return 0.4 + 0.6 * (1 - min(option["one_way_hours"], 20) / 20)
    return 1.0 if option["mode"] == preference else 0.3


def normalise_weights(weights=None):
    """Fill in missing weights from the defaults and scale them to sum to 1."""
    merged = dict(DEFAULT_WEIGHTS)
    if weights:
        merged.update(weights)
    total = sum(merged.values())
    if total <= 0:
        return dict(DEFAULT_WEIGHTS)
    return {k: v / total for k, v in merged.items()}


# -------------------------------------------------------------- explanations
def build_reasons(dest, req, option, tier, activities, cost, components, matched, duration_note, category_labels):
    """Plain-English reasons shown to the traveller."""
    reasons = []
    if req["category"] != "any":
        label = category_labels.get(req["category"], req["category"])
        if dest["category"] == req["category"]:
            reasons.append(f"Matches your preferred type ({label}).")
        else:
            reasons.append(f"{dest['name']} is mainly {category_labels[dest['category']]} but also offers {label.lower()} experiences.")
    if req["interests"]:
        if matched:
            reasons.append(f"Covers {len(matched)} of your {len(req['interests'])} interests: {', '.join(m.replace('_', ' ') for m in matched)}.")
        else:
            reasons.append("Does not directly cover your selected interests.")
    reasons.append(f"Trip length: {duration_note}.")
    pct = round(100 * cost["total"] / req["budget"])
    reasons.append(f"Estimated total is {pct}% of your budget, leaving ₹{req['budget'] - cost['total']:,} spare.")
    if req["transport"] == "auto":
        reasons.append(f"{option['label']} chosen for a good balance of time ({option['one_way_hours']} h each way) and cost.")
    elif option["mode"] == req["transport"]:
        reasons.append(f"Uses your preferred transport ({option['label']}).")
    else:
        reasons.append(f"Your preferred transport is not available or practical for this route; {option['label']} is used instead.")
    reasons.append(f"{tier.title()} accommodation: {cost['rooms']} room(s) x {cost['nights']} night(s).")
    return reasons
