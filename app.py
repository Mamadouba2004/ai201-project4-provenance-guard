"""
app.py — Provenance Guard: AI text-provenance detection API.

Endpoints:
  POST /submit      — submit text for AI-provenance classification
  POST /appeal      — appeal a classification decision
  GET  /health      — liveness check
  GET  /log         — view recent audit entries
"""

import uuid

from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv

from detector import analyze_text
from audit import log_request, get_recent_logs, get_by_content_id, log_appeal

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

@app.route("/submit", methods=["POST"])
@limiter.limit("10 per minute;100 per day")
def submit():
    """
    Submit text for AI-provenance classification.

    Request body (JSON):
      { "text": "<text to analyze>", "creator_id": "<submitter id>" }

    Response (JSON):
      {
        "content_id": "<uuid>",
        "creator_id": "<submitter id>",
        "prediction": "human" | "ai",
        "attribution": "likely_ai" | "uncertain" | "likely_human",
        "confidence": 0.0-1.0,
        "label": "<transparency label text>",
        "signals": [ { signal details }, ... ],
        "text_length": <int>
      }
    """
    data = request.get_json(silent=True)

    if not data or "text" not in data:
        return jsonify({"error": "Request body must be JSON with a 'text' field."}), 400

    text = data["text"].strip()
    creator_id = data.get("creator_id", "anonymous")

    if len(text) < 30:
        return jsonify({"error": "Text is too short for reliable analysis (min 30 chars)."}), 400

    if len(text) > 10_000:
        return jsonify({"error": "Text exceeds maximum length of 10,000 characters."}), 400

    content_id = str(uuid.uuid4())
    result = analyze_text(text)
    log_request(content_id, creator_id, text, result)

    return jsonify({
        "content_id": content_id,
        "creator_id": creator_id,
        **result,
    }), 200


@app.route("/appeal", methods=["POST"])
@limiter.limit("10 per minute;100 per day")
def appeal():
    """
    Appeal a classification decision.

    Request body (JSON):
      { "content_id": "<uuid from /submit>", "creator_reasoning": "<why>" }

    On success: the original submission's status flips to 'under_review',
    the reasoning is recorded in the audit log, and a confirmation is
    returned. Automated re-classification is intentionally out of scope —
    a human reviewer picks it up from the 'under_review' queue.
    """
    data = request.get_json(silent=True)

    if not data or "content_id" not in data or "creator_reasoning" not in data:
        return jsonify({
            "error": "Request body must be JSON with 'content_id' and 'creator_reasoning' fields."
        }), 400

    content_id = data["content_id"]
    creator_reasoning = data["creator_reasoning"].strip()

    if not creator_reasoning:
        return jsonify({"error": "creator_reasoning must not be empty."}), 400

    original = get_by_content_id(content_id)
    if original is None:
        return jsonify({"error": f"No submission found for content_id '{content_id}'."}), 404

    log_appeal(content_id, creator_reasoning)

    return jsonify({
        "status": "under_review",
        "content_id": content_id,
        "message": "Your appeal has been received and the classification is now under review.",
        "original_attribution": original["attribution"],
        "original_confidence": original["confidence"],
    }), 200


@app.route("/health", methods=["GET"])
def health():
    """Simple liveness probe."""
    return jsonify({"status": "ok"}), 200


@app.route("/log", methods=["GET"])
def log():
    """Return the most recent audit entries."""
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
