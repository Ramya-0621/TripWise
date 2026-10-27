"""
app.py  -  FLASK REST API
=========================
Endpoints
    GET  /api/health          server status
    GET  /api/options         values for the form (cities, categories, interests ...)
    GET  /api/destinations    all destinations (optional ?category=beach)
    GET  /api/destination/<id>
    POST /api/recommend       body: travel preferences (JSON) -> ranked itineraries

The same server also serves the frontend, so http://127.0.0.1:5000/ works with
no extra tools. If you prefer VS Code Live Server (port 5500), the CORS headers
below let the page call this API from another port (development only).
"""
import logging
import os
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from knowledge_base import KnowledgeBaseError, get_kb
from recommender import ValidationError, recommend

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = Flask(__name__, static_folder=None)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("tripwise")


# ----------------------------------------------------------------- CORS
@app.after_request
def add_cors_headers(response):
    """Development CORS so Live Server (another port) can call this API.
    There are no cookies or secrets, so a wildcard origin is acceptable locally.
    Restrict this before deploying anywhere public."""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


# ------------------------------------------------------------- frontend
@app.get("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.get("/<path:filename>")
def frontend_files(filename):
    if filename.startswith("api/"):
        # The catch-all would otherwise hide Flask's own 405 for POST-only routes.
        if filename == "api/recommend":
            return jsonify({"error": "Method not allowed. Use POST with a JSON body."}), 405
        return jsonify({"error": "Not found"}), 404
    return send_from_directory(FRONTEND_DIR, filename)


# ------------------------------------------------------------------ API
@app.get("/api/health")
def health():
    kb = get_kb()
    return jsonify({"status": "ok", "app": "TripWise", "destinations": len(kb.destinations)})


@app.get("/api/options")
def options():
    return jsonify(get_kb().options())


@app.get("/api/destinations")
def destinations():
    kb = get_kb()
    category = request.args.get("category")
    items = kb.destinations
    if category:
        if category not in kb.category_ids:
            return jsonify({"error": f"Unknown category '{category}'.", "valid": kb.category_ids}), 400
        items = [d for d in items if d["category"] == category]
    return jsonify({"count": len(items), "destinations": [kb.public_destination(d) for d in items]})


@app.get("/api/destination/<dest_id>")
def destination(dest_id):
    kb = get_kb()
    dest = kb.get_destination(dest_id)
    if dest is None:
        return jsonify({"error": f"Destination '{dest_id}' not found."}), 404
    return jsonify(kb.public_destination(dest))


@app.post("/api/recommend")
def api_recommend():
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({"error": "Request body must be valid JSON with Content-Type: application/json."}), 400
    try:
        return jsonify(recommend(payload))
    except ValidationError as exc:
        return jsonify({"error": "Invalid input.", "details": exc.details}), 400
    except Exception:           # never leak a stack trace to the browser
        log.exception("Recommendation failed")
        return jsonify({"error": "Something went wrong while planning your trip. Please try again."}), 500


# -------------------------------------------------------- error handlers
@app.errorhandler(404)
def not_found(_):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(405)
def method_not_allowed(_):
    return jsonify({"error": "Method not allowed"}), 405


if __name__ == "__main__":
    try:
        get_kb()                # fail fast if the JSON files are broken
    except KnowledgeBaseError as exc:
        raise SystemExit(f"Knowledge base error: {exc}")
    port = int(os.environ.get("PORT", 5000))
    print(f"TripWise running at http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=True)
