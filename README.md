# Provenance Guard

An AI text-provenance detection API. Submit a piece of text and Provenance Guard
returns a transparency label estimating whether it was **likely human-written**,
**likely AI-generated**, or **uncertain** — backed by two independent detection
signals, a calibrated confidence score, an appeals workflow, rate limiting, and a
structured audit log.

> Built for AI-201 Project 4. See [planning.md](planning.md) for the full spec
> and architecture diagram this implementation was built against.

---

## Architecture

A submitted text always passes through **both** detection signals independently
before scoring; neither short-circuits the other, so the combined score always
reflects two genuinely distinct measurements.

```
POST /submit { text, creator_id }
        │
        ▼
   Flask app (app.py) ── assigns content_id (uuid)
        │
        ├─► Signal 1: Groq LLM classifier   → p_human_llm
        └─► Signal 2: Stylometric heuristics → p_human_style
        │
        ▼
   Confidence scoring (detector.py)
   combined = 0.60·p_human_llm + 0.40·p_human_style
        │
        ▼
   Transparency label (3 bands)
        │
        ▼
   Audit log (SQLite) — content_id, both signal scores, combined, status
        │
        ▼
   Response { content_id, attribution, confidence, label, signals[] }


POST /appeal { content_id, creator_reasoning }
        │
        ▼
   Look up content_id → status flips to "under_review"
        │                (original label/score preserved, now disputed)
        ▼
   Audit log updated in place — appeal_reasoning + appealed_at recorded
        │
        ▼
   Response { status: "under_review", content_id, message }
```

An appeal never mutates the original signal outputs or label — it only adds
status and reasoning to the same row, so the original automated assessment stays
fully reconstructable even after a human overturns it.

---

## API

| Endpoint  | Method | Body                                      | Returns |
|-----------|--------|-------------------------------------------|---------|
| `/submit` | POST   | `{text, creator_id}`                      | `content_id`, `attribution`, `confidence`, `label`, `signals[]` |
| `/appeal` | POST   | `{content_id, creator_reasoning}`         | `status: under_review`, confirmation |
| `/log`    | GET    | —                                         | recent audit entries (JSON) |
| `/health` | GET    | —                                         | `{status: ok}` |

---

## Setup

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file in the repo root (it is git-ignored — never commit it):

```
GROQ_API_KEY=your_key_here
```

Run the server:

```bash
python app.py
```

> **Note (macOS):** port 5000 is often occupied by AirPlay Receiver. If `/health`
> returns `403 AirTunes`, disable *AirPlay Receiver* in System Settings, or run on
> another port: `python -c "from app import app; app.run(port=5050)"`.

---

## Detection Signals — and why these two

The system requires two signals that capture **genuinely different** properties of
the text. A weak pairing is two versions of the same idea; this pairing is one
**semantic** signal and one **structural** signal, so they fail in different ways
and the combination is more informative than either alone.

### Signal 1 — LLM classifier (Groq `llama-3.3-70b-versatile`)

- **Measures:** holistic semantic/stylistic coherence — does the text *read* like
  something a human would produce (argument structure, idiom, hedging, generic
  transitions).
- **Why it works:** LLMs are sensitive to global patterns — over-balanced
  arguments, "it is important to note," generic connective tissue — that are hard
  to detect by counting but jump out semantically.
- **Blind spot:** it's a black box. Its "reasoning" is a post-hoc justification,
  not a cause, so it can be confidently wrong — especially on very short text or on
  neutral/formal human writing (legal, technical) that it conflates with AI output.

### Signal 2 — Stylometric heuristics (pure Python, no ML)

- **Measures:** surface statistics — sentence-length standard deviation, type-token
  ratio (vocabulary diversity), punctuation density, average word length.
- **Why it works:** AI text trends toward statistical uniformity (even sentence
  lengths, predictable vocabulary, sparse punctuation variety); human writing is
  more irregular.
- **Blind spot:** it understands nothing. A human who writes in short, uniform
  sentences (a non-native speaker, a style guide, a child) scores "AI" on this
  signal, and an AI told to "vary your sentence length and add personality" defeats
  every metric here trivially.

---

## Confidence Scoring — and why this approach

Each signal emits `(prediction, confidence)`. We convert each to a **probability
that the text is human** (`p_human`), then take a **weighted average**:

```
combined = 0.60 · p_human_llm + 0.40 · p_human_style
```

The LLM is weighted higher because it captures semantics the heuristics
structurally cannot — but at 40%, the stylometric signal still meaningfully pulls
the score when the two disagree. That's the whole point of two signals: the
disagreement carries information.

`combined` is a continuous value in `[0, 1]`, **not a binary flip at 0.5**. It maps
to three label bands:

| `combined` (p_human) | Label band            |
|----------------------|------------------------|
| `0.00 – 0.40`         | Likely AI-generated    |
| `0.40 – 0.60`         | **Uncertain**          |
| `0.60 – 1.00`         | Likely human-written   |

The middle band exists so the system never manufactures a confident-sounding label
out of a near-coin-flip. A 0.52 and a 0.58 both land in "Uncertain," which is the
honest description of what the system actually knows there.

### Two example submissions (actual scores from testing)

**High-confidence case — casual human writing → `combined = 0.84`:**

> *"ok so i finally tried that new ramen place downtown and honestly? underwhelming.
> the broth was fine but they put WAY too much sodium in it..."*

- LLM: `human` @ 0.90 → `p_human_llm = 0.90`
- Stylometric: `human` @ 0.75 → `p_human_style = 0.75`
- **combined = 0.84 → "Likely human-written"**
- Both signals agreed; high confidence.

**Lower-confidence case — formal human econ writing → `combined = 0.56`:**

> *"The relationship between monetary policy and asset price inflation has been
> extensively studied in the literature. Central banks face a fundamental tension
> between their mandate for price stability..."*

- LLM: `human` @ 0.80 → `p_human_llm = 0.80`
- Stylometric: `ai` @ 0.80 → `p_human_style = 0.20` (zero punctuation variety,
  even sentence length — reads "AI-like" structurally)
- **combined = 0.56 → "Uncertain"**
- The signals *disagreed*, and the scoring correctly refused to force a confident
  label. This is exactly the behavior a single signal can't produce.

These two cases span from 0.84 down to 0.56 — meaningful variation, not a constant.

---

## Transparency Label — all three variants (verbatim)

The label returned by `/submit` changes with the confidence score; all three
disclose that the result is automated and can be wrong.

**High-confidence AI** (`combined ≤ 0.40`):

> This text is likely AI-generated (confidence: NN%). This assessment is based on
> automated signals and may be incorrect — see our appeals process if you believe
> this is wrong.

**High-confidence human** (`combined ≥ 0.60`):

> This text is likely human-written (confidence: NN%). This assessment is based on
> automated signals and may be incorrect.

**Uncertain** (`0.40 < combined < 0.60`):

> This text's origin could not be reliably determined (confidence: NN%). Automated
> signals were inconclusive — treat this result as inconclusive, not as evidence of
> AI use.

The "Uncertain" wording is deliberately worded to discourage anyone from reading an
inconclusive result as a soft accusation.

---

## Appeals Workflow

Anyone holding the `content_id` from a `/submit` response can file an appeal:

```bash
curl -s -X POST http://localhost:5050/appeal \
  -H "Content-Type: application/json" \
  -d '{"content_id": "PASTE-CONTENT-ID", "creator_reasoning": "I wrote this myself. I am a non-native English speaker and my style may appear more formal than typical."}'
```

On receipt the system: (1) flips the submission's status to `under_review`,
(2) records `creator_reasoning` + `appealed_at` **on the original audit row** so the
appeal is tied to the original decision, and (3) returns a confirmation. The
original label and confidence are **not** hidden or changed — they remain visible,
now flagged as disputed, for a human reviewer. Automated re-classification is out
of scope by design; a human picks it up from the `under_review` queue.

An unknown `content_id` returns **404**.

---

## Rate Limiting

`/submit` and `/appeal` are limited via Flask-Limiter to:

```
10 per minute; 100 per day
```

**Reasoning:** a real creator checking their own work submits a handful of pieces
in a sitting — 10/minute comfortably covers that with room for retries, while
stopping a script from flooding the (paid, Groq-backed) classifier. 100/day caps
sustained abuse from a single IP without getting in a legitimate user's way. The
numbers are usage-shaped, not arbitrary: the binding constraint is that every
`/submit` costs a Groq API call.

**Verified behavior** — 12 rapid requests, first 10 succeed then the limiter kicks
in:

```
200
200
200
200
200
200
200
200
200
200
429
429
```

The 429 response body is `{"error": "Rate limit exceeded. Please slow down."}`.

---

## Audit Log

Every submission writes a structured SQLite row; `GET /log` returns them as JSON.
Each entry captures: `timestamp`, `content_id`, `creator_id`, `attribution`,
`confidence`, both individual signal scores (`llm_score`, `stylometric_score`), the
full raw `signals`, `status`, and — once appealed — `appeal_reasoning` +
`appealed_at`.

Example entry after an appeal (abridged):

```json
{
  "content_id": "63a91893-c432-4594-adac-2ac2c781a7af",
  "creator_id": "appellant-1",
  "timestamp": "2026-07-06T04:36:52Z",
  "attribution": "uncertain",
  "confidence": 0.56,
  "llm_score": 0.8,
  "stylometric_score": 0.2,
  "status": "under_review",
  "appeal_reasoning": "I wrote this myself from personal experience. I am a non-native English speaker...",
  "appealed_at": "2026-07-06T04:36:54Z"
}
```

---

## Known Limitations

**Formal human writing by non-native English speakers is systematically
under-protected.** ESL writers often produce grammatically correct, evenly-paced,
low-punctuation-variety prose (short declaratives, few semicolons/dashes) as a
deliberate strategy — and that pattern is exactly what the **stylometric signal**
reads as "AI-like." In testing, a genuine human-written economics paragraph scored
`stylometric = 0.20` (strongly "AI") purely because it had zero punctuation variety
and uniform sentence length; only the LLM signal kept the overall verdict at
"Uncertain" rather than "Likely AI." This is a fairness problem, not just an
accuracy one: the tool risks flagging non-native speakers' authentic work more
often than native speakers'. It's tied directly to a property of Signal 2 — it
measures surface regularity, and formal/ESL writing is legitimately regular. **This
tool should never be used as sole evidence for a punitive decision.**

(A second known-weak case: short, repetitive creative writing such as
nursery-rhyme-style poetry, which the stylometric signal's low type-token-ratio and
low sentence-variance checks will read as AI.)

---

## Spec Reflection

**How the spec helped:** Writing the three label variants *verbatim* in planning.md
before any UI code meant the `_label_for()` function had an exact target — I
implemented the thresholds and copy directly from §3 rather than inventing wording
mid-build, and the band cutoffs (0.40 / 0.60) were already decided, so scoring and
labeling never drifted apart.

**How the implementation diverged:** planning.md specified a richer appeals model —
a `contact` field on submit and separate `/appeals` queue + `/appeals/{id}/resolve`
reviewer endpoints. The Milestone 5 build followed the assignment's simpler contract
instead: `creator_reasoning` (not `contact`/`reason`), status `under_review` (not
`appeal_pending`), and a single `/appeal` endpoint with review left as an offline
step against the `under_review` rows. I diverged to match the grader's exact curl
contract; the reviewer-queue endpoints remain a documented next step.

---

## AI Usage

**1. Scaffolding the two-signal detector.** I directed the AI to generate the
stylometric signal function and the ensemble combiner from the detection-signals and
uncertainty sections of planning.md. It produced a reasonable `analyze_text` that
combined the signals — but I overrode its scoring: its first version leaned on a
plain average and didn't emit the individual `llm_score`/`stylometric_score` the
audit log needs, so I fixed the 60/40 weighting and had it surface both per-signal
`p_human` values in the return payload.

**2. Label banding.** I asked the AI to map confidence scores to the three label
variants. Its draft implemented reasonable-looking cutoffs that **silently diverged**
from my spec (it used a 0.5 midpoint split rather than the 0.40/0.60 three-band
scheme). I caught this against planning.md §2, corrected the thresholds, and pasted
in the exact label copy so the output matched the spec rather than the AI's
plausible-but-wrong guess.
