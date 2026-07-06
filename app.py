"""
app.py — Provenance Guard: AI text-provenance detection API.

Endpoints:
  POST /analyze     — detect whether text is human or AI-generated
  GET  /health      — liveness check
  GET  /logs        — view recent audit entries
"""

from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv

from detector import analyze_text
from audit import log_request, get_recent_logs

load_dotenv()

app = Flask(__name__)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "30 per hour"],
    storage_uri="memory://",
)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/analyze", methods=["POST"])
@limiter.limit("10 per minute")
def analyze():
    """
    Analyze submitted text for AI provenance.

    Request body (JSON):
      { "text": "<text to analyze>" }

    Response (JSON):
      {
        "prediction": "human" | "ai",
        "confidence": 0.0–1.0,
        "signals": [ { signal details }, ... ],
        "text_length": <int>
      }
    """
    data = request.get_json(silent=True)

    if not data or "text" not in data:
        return jsonify({"error": "Request body must be JSON with a 'text' field."}), 400

    text = data["text"].strip()

    if len(text) < 30:
        return jsonify({"error": "Text is too short for reliable analysis (min 30 chars)."}), 400

    if len(text) > 10_000:
        return jsonify({"error": "Text exceeds maximum length of 10,000 characters."}), 400

    result = analyze_text(text)
    log_request(text, result)

    return jsonify(result), 200


@app.route("/health", methods=["GET"])
def health():
    """Simple liveness probe."""
    return jsonify({"status": "ok"}), 200


@app.route("/logs", methods=["GET"])
def logs():
    """Return the 20 most recent audit entries."""
    limit = request.args.get("limit", 20, type=int)
    entries = get_recent_logs(limit=min(limit, 100))
    return jsonify({"count": len(entries), "entries": entries}), 200


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(429)
def rate_limit_hit(e):
    return jsonify({"error": "Rate limit exceeded. Please slow down."}), 429


@app.errorhandler(500)
def internal_error(e):
    return jsonify({"error": "Internal server error."}), 500


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True, port=5000)
