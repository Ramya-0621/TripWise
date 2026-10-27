"""
knowledge_base.py  -  KNOWLEDGE STORAGE LAYER
=============================================
Loads the JSON files in backend/data/ and exposes them as plain Python
dictionaries and lists. No recommendation logic lives here: this module only
reads, validates and looks things up, so you can edit the JSON files without
touching the algorithms.

Files:
    data/destinations.json  - destinations, activities, illustrative costs
    data/reference.json     - categories, interests, transport rates, cities
"""
import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"

REQUIRED_DESTINATION_FIELDS = [
    "id", "name", "state", "category", "description", "days", "lat", "lon",
    "access", "transfer_cost_pp", "accommodation_per_room_night",
    "food_per_person_day", "local_transport_per_vehicle_day", "tags", "activities",
]


class KnowledgeBaseError(Exception):
    """Raised when a JSON data file is missing or malformed."""


def _load_json(filename):
    path = DATA_DIR / filename
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise KnowledgeBaseError(f"Data file not found: {path}")
    except json.JSONDecodeError as exc:
        raise KnowledgeBaseError(f"{filename} is not valid JSON: {exc}")


class KnowledgeBase:
    """In-memory view of the travel knowledge."""

    def __init__(self):
        raw = _load_json("destinations.json")
        self.reference = _load_json("reference.json")
        self.destinations = raw["destinations"]
        self._validate()

        self.by_id = {d["id"]: d for d in self.destinations}
        self.category_ids = [c["id"] for c in self.reference["categories"]]
        self.category_labels = {c["id"]: c["label"] for c in self.reference["categories"]}
        self.interest_ids = [i["id"] for i in self.reference["interests"]]
        self.tier_ids = [t["id"] for t in self.reference["accommodation_tiers"]]
        self.transport_modes = self.reference["transport_modes"]

        # City lookup: lower-case name or alias -> city record
        self._cities = {}
        for city in self.reference["cities"]:
            self._cities[city["name"].lower()] = city
            for alias in city.get("aliases", []):
                self._cities[alias.lower()] = city

    # ------------------------------------------------------------------ checks
    def _validate(self):
        """Fail early with a clear message if a destination record is incomplete."""
        seen = set()
        for d in self.destinations:
            for field in REQUIRED_DESTINATION_FIELDS:
                if field not in d:
                    raise KnowledgeBaseError(f"Destination '{d.get('id', '?')}' is missing field '{field}'")
            if d["id"] in seen:
                raise KnowledgeBaseError(f"Duplicate destination id '{d['id']}'")
            seen.add(d["id"])

    # ----------------------------------------------------------------- lookups
    def get_destination(self, dest_id):
        return self.by_id.get(dest_id)

    def find_city(self, name):
        """Return the city record for a name/alias (case-insensitive) or None."""
        return self._cities.get((name or "").strip().lower())

    def city_names(self):
        return sorted(c["name"] for c in self.reference["cities"])

    def options(self):
        """Everything the frontend needs to build its form."""
        return {
            "cities": self.city_names(),
            "categories": self.reference["categories"],
            "interests": self.reference["interests"],
            "transport_modes": [{"id": "auto", "label": "Auto (compare all)"}] +
                               [{"id": k, "label": v["label"]} for k, v in self.transport_modes.items()],
            "accommodation_tiers": self.reference["accommodation_tiers"],
        }

    def public_destination(self, d):
        """Destination fields that are safe/useful to send to the browser."""
        return {
            "id": d["id"], "name": d["name"], "state": d["state"],
            "category": d["category"], "category_label": self.category_labels.get(d["category"], d["category"]),
            "secondary_categories": d.get("secondary_categories", []),
            "description": d["description"], "best_season": d.get("best_season"),
            "days": d["days"], "tags": d["tags"], "wiki_title": d.get("wiki_title"),
            "lat": d["lat"], "lon": d["lon"], "access": d["access"],
            "activities": d["activities"],
            "accommodation_per_room_night": d["accommodation_per_room_night"],
            "food_per_person_day": d["food_per_person_day"],
            "local_transport_per_vehicle_day": d["local_transport_per_vehicle_day"],
            "estimates_note": "Illustrative estimates, not live prices.",
        }


_kb_instance = None


def get_kb():
    """Load once and reuse (the JSON files are small)."""
    global _kb_instance
    if _kb_instance is None:
        _kb_instance = KnowledgeBase()
    return _kb_instance
