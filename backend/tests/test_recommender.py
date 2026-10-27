"""
Automated tests for TripWise. Run from the TripWise folder:

    python -m unittest discover -s backend/tests -v

They cover the 8 required scenarios plus budget maths, hard constraints,
the knowledge-base JSON files and the Flask API.
"""
import json
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import rules                                    # noqa: E402
from app import app                             # noqa: E402
from knowledge_base import get_kb, DATA_DIR     # noqa: E402
from recommender import recommend, ValidationError  # noqa: E402
from search_algorithms import bfs_search, filter_destinations, top_k  # noqa: E402

KB = get_kb()


def check_invariants(test, result, query):
    """Rules every returned itinerary must obey, whatever the scenario."""
    for it in result["itineraries"]:
        b = it["budget"]
        parts = b["transport"] + b["accommodation"] + b["food"] + b["local_transport"] + b["activities"]
        test.assertEqual(parts, b["total"], "cost parts must add up to the total (no double counting)")
        test.assertLessEqual(b["total"], query["budget"], "R5: total must not exceed budget")
        test.assertEqual(b["remaining"], query["budget"] - b["total"])
        dest = KB.get_destination(it["destination"]["id"])
        test.assertGreaterEqual(query["days"], dest["days"]["min"], "R4: trip must meet the minimum days")
        test.assertTrue(it["transport"]["total"] > 0)
        test.assertGreaterEqual(it["score"], 0)
        test.assertLessEqual(it["score"], 100)
        # R7: round-trip travel time <= 40% of the trip
        test.assertLessEqual(2 * it["transport"]["one_way_hours"], 0.4 * query["days"] * 24 + 1e-9)
        # R10: activities fit in the available half-day slots
        test.assertLessEqual(sum(a["slots"] for a in it["activities"]), rules.slots_available(query["days"]))
    scores = [it["score"] for it in result["itineraries"]]
    test.assertEqual(scores, sorted(scores, reverse=True), "results must be ranked best-first")
    test.assertLessEqual(len(scores), 5)


class ScenarioTests(unittest.TestCase):
    def test_1_low_budget_nature_trip(self):
        q = dict(starting_city="Delhi", budget=18000, days=4, travelers=2, category="nature")
        r = recommend(q)
        self.assertGreaterEqual(r["count"], 1)
        check_invariants(self, r, q)
        for it in r["itineraries"]:
            d = KB.get_destination(it["destination"]["id"])
            self.assertTrue(d["category"] == "nature" or "nature" in d["secondary_categories"])

    def test_2_high_budget_luxury_trip(self):
        q = dict(starting_city="Mumbai", budget=300000, days=6, travelers=2, accommodation="luxury")
        r = recommend(q)
        self.assertEqual(r["count"], 5)
        check_invariants(self, r, q)
        for it in r["itineraries"]:
            self.assertEqual(it["accommodation"]["tier"], "luxury")
            d = KB.get_destination(it["destination"]["id"])
            self.assertEqual(it["accommodation"]["rate_per_room_night"], d["accommodation_per_room_night"]["luxury"])

    def test_3_beach_trip_with_bus_preference(self):
        q = dict(starting_city="Hyderabad", budget=40000, days=5, travelers=2, category="beach", transport="bus")
        r = recommend(q)
        self.assertGreaterEqual(r["count"], 1)
        check_invariants(self, r, q)
        for it in r["itineraries"]:
            self.assertEqual(it["destination"]["category"], "beach")
            self.assertEqual(it["transport"]["mode"], "bus", "R8: preferred mode kept when feasible")

    def test_4_cultural_trip_short_duration(self):
        q = dict(starting_city="Delhi", budget=25000, days=2, travelers=2, category="historical")
        r = recommend(q)
        self.assertGreaterEqual(r["count"], 1)
        check_invariants(self, r, q)
        names = [it["destination"]["name"] for it in r["itineraries"]]
        self.assertNotIn("Udaipur", names)       # needs at least 3 days

    def test_5_interest_based_trip(self):
        q = dict(starting_city="Bengaluru", budget=60000, days=5, travelers=2,
                 interests=["trekking", "photography", "wildlife"])
        r = recommend(q)
        self.assertGreaterEqual(r["count"], 3)
        check_invariants(self, r, q)
        self.assertIsNone(r["relaxed"])
        for it in r["itineraries"]:
            pool = set(it["destination"]["tags"])
            self.assertTrue(pool & {"trekking", "photography", "wildlife"})

    def test_6_impossible_budget_gives_helpful_message(self):
        r = recommend(dict(starting_city="Chennai", budget=2000, days=4, travelers=2))
        self.assertEqual(r["count"], 0)
        self.assertEqual(r["itineraries"], [])
        self.assertTrue(r["suggestions"])
        self.assertIn("budget", " ".join(r["suggestions"]).lower())

    def test_6b_trip_too_short_for_anything(self):
        r = recommend(dict(starting_city="Chennai", budget=500000, days=1, travelers=1))
        self.assertEqual(r["count"], 0)
        self.assertIn("days", " ".join(r["suggestions"]))

    def test_7_invalid_or_missing_input(self):
        with self.assertRaises(ValidationError) as ctx:
            recommend({})
        self.assertGreaterEqual(len(ctx.exception.details), 3)
        bad_inputs = [
            dict(starting_city="Atlantis", budget=10000, days=3),
            dict(starting_city="Delhi", budget="abc", days=3),
            dict(starting_city="Delhi", budget=10000, days=0),
            dict(starting_city="Delhi", budget=10000, days=3, travelers=0),
            dict(starting_city="Delhi", budget=10000, days=3, interests=["skydiving"]),
            dict(starting_city="Delhi", budget=10000, days=3, category="moon"),
            dict(starting_city="Delhi", budget=True, days=3),
            "not a dict",
        ]
        for bad in bad_inputs:
            with self.assertRaises(ValidationError, msg=str(bad)):
                recommend(bad)

    def test_8_multiple_travelers_scale_costs(self):
        base = dict(starting_city="Pune", budget=500000, days=5, category="beach", transport="train",
                    accommodation="standard")
        one = recommend({**base, "travelers": 1})
        four = recommend({**base, "travelers": 4})
        check_invariants(self, four, {**base, "travelers": 4})
        for a in one["itineraries"]:
            b = next(x for x in four["itineraries"] if x["destination"]["id"] == a["destination"]["id"])
            self.assertAlmostEqual(b["budget"]["transport"], 4 * a["budget"]["transport"])
            self.assertGreater(b["budget"]["food"], 3.9 * a["budget"]["food"])
            self.assertEqual(b["accommodation"]["rooms"], 2)               # 4 travelers -> 2 rooms
            self.assertEqual(a["accommodation"]["rooms"], 1)
            self.assertLess(b["budget"]["accommodation"], 4 * a["budget"]["accommodation"] + 1)  # rooms are shared


class RuleAndCostTests(unittest.TestCase):
    def test_cost_model_by_hand(self):
        dest = KB.get_destination("goa")
        opt = {"mode": "bus", "fare_pp_round_trip": 2000, "one_way_hours": 10, "label": "Bus", "distance_km": 600, "transfer_pp": 0}
        acts = [dest["activities"][1]]        # Old Goa, Rs 200 pp
        c = rules.calculate_cost(dest, opt, "standard", acts, travelers=3, days=4)
        self.assertEqual(c["transport"], 6000)
        self.assertEqual(c["rooms"], 2)
        self.assertEqual(c["nights"], 3)
        self.assertEqual(c["accommodation"], 3500 * 2 * 3)
        self.assertEqual(c["food"], 900 * 1.0 * 4 * 3)
        self.assertEqual(c["local_transport"], 700 * 1 * 4)
        self.assertEqual(c["activities"], 200 * 3)
        self.assertEqual(c["total"], 6000 + 21000 + 10800 + 2800 + 600)

    def test_duration_rule(self):
        d = KB.get_destination("ladakh")                     # min 5, ideal 7, max 10
        self.assertEqual(rules.rule_duration_status(d, 4)[0], "reject")
        self.assertLess(rules.rule_duration_status(d, 5)[1], 1.0)
        self.assertEqual(rules.rule_duration_status(d, 8)[1], 1.0)
        self.assertLess(rules.rule_duration_status(d, 12)[1], 1.0)

    def test_weights_are_normalised_and_configurable(self):
        w = rules.normalise_weights({"interest": 1, "category": 0, "budget_fit": 0, "duration": 0, "transport": 0})
        self.assertAlmostEqual(sum(w.values()), 1.0)
        self.assertAlmostEqual(w["interest"], 1.0)
        r = recommend(dict(starting_city="Delhi", budget=60000, days=4, travelers=2,
                           weights={"budget_fit": 10}))
        self.assertGreater(r["weights_used"]["budget_fit"], 0.8)

    def test_bfs_prunes_before_expanding(self):
        r = recommend(dict(starting_city="Delhi", budget=18000, days=4, travelers=2, category="nature"))
        self.assertGreater(r["stats"]["bfs_nodes_pruned"], 0)

    def test_generic_search_helpers(self):
        kept, rejected = filter_destinations([{"id": 1}, {"id": 2}, {"id": 3}],
                                             [("even only", lambda d: d["id"] % 2 == 0)])
        self.assertEqual([d["id"] for d in kept], [2])
        self.assertEqual(rejected["even only"], [1, 3])
        self.assertEqual(top_k([3, 9, 1, 7], 2, key=lambda x: x), [9, 7])

        class S:                                  # tiny BFS: count from 0 to 3
            def __init__(self, n): self.n, self.stage = n, "x"
        goals, stats = bfs_search(S(0), lambda s: [S(s.n + 1), S(s.n + 2)], lambda s: s.n == 3,
                                  prune=lambda c: c.n > 3)
        self.assertTrue(goals)
        self.assertGreater(stats["pruned"], 0)


class KnowledgeBaseTests(unittest.TestCase):
    def test_json_files_are_valid_and_complete(self):
        for name in ("destinations.json", "reference.json"):
            with open(DATA_DIR / name, encoding="utf-8") as f:
                json.load(f)
        self.assertGreaterEqual(len(KB.destinations), 15)
        categories = {d["category"] for d in KB.destinations}
        self.assertEqual(categories, set(KB.category_ids), "every category needs at least one destination")
        for d in KB.destinations:
            self.assertGreaterEqual(len(d["activities"]), 3)
            self.assertTrue(set(d["tags"]) <= set(KB.interest_ids), d["id"])
            for a in d["activities"]:
                self.assertTrue(set(a["tags"]) <= set(KB.interest_ids), d["id"])
            self.assertTrue(any(d["access"].values()), d["id"])
            for mode, ok in d["access"].items():
                if ok:
                    self.assertIn(mode, d["transfer_cost_pp"], f"{d['id']} needs transfer_cost_pp for {mode}")


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_health(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["status"], "ok")

    def test_destinations_and_single_destination(self):
        r = self.client.get("/api/destinations")
        self.assertGreaterEqual(r.get_json()["count"], 15)
        self.assertEqual(self.client.get("/api/destinations?category=beach").status_code, 200)
        self.assertEqual(self.client.get("/api/destinations?category=zzz").status_code, 400)
        self.assertEqual(self.client.get("/api/destination/goa").get_json()["name"], "Goa")
        self.assertEqual(self.client.get("/api/destination/nope").status_code, 404)

    def test_options(self):
        data = self.client.get("/api/options").get_json()
        self.assertIn("Hyderabad", data["cities"])
        self.assertEqual(len(data["categories"]), 6)

    def test_recommend_ok_and_errors(self):
        good = {"starting_city": "Hyderabad", "budget": 40000, "days": 5, "travelers": 2, "category": "beach"}
        r = self.client.post("/api/recommend", json=good)
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(r.get_json()["count"], 1)
        self.assertEqual(self.client.post("/api/recommend", json={}).status_code, 400)
        self.assertEqual(self.client.post("/api/recommend", data="not json",
                                          content_type="text/plain").status_code, 400)
        self.assertEqual(self.client.get("/api/recommend").status_code, 405)
        self.assertEqual(self.client.get("/api/nothing").status_code, 404)

    def test_frontend_is_served(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"TripWise", r.data)
        r.close()


if __name__ == "__main__":
    unittest.main()
