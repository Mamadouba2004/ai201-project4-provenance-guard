# Provenance Guard — Planning

## 1. Detection Signals

**Signal 1 — LLM Classifier (Groq, `llama-3.3-70b-versatile`)**
- **Measures:** Holistic semantic and stylistic coherence — does the text "read" like something a human would produce, based on the model's learned sense of naturalness, argument structure, and idiomatic phrasing.
- **Why it differs:** LLMs are highly sensitive to global patterns (repetitive framing, hedging language, overly balanced argument structure, generic transitions like "in conclusion" / "it's important to note") that are common in AI-generated text but require semantic understanding, not just counting, to detect.
- **Blind spot:** It is a black box — its "reasoning" is a post-hoc justification, not a causal explanation, so it can be confidently wrong, especially on very short text, non-English or code-mixed text, or text a human wrote in a deliberately neutral/formal register (e.g., legal or technical writing), which the model conflates with AI output.
- **Output shape:** `{"prediction": "human"|"ai", "confidence": float 0.0-1.0, "reasoning": str}`

**Signal 2 — Stylometric Heuristics (pure Python)**
- **Measures:** Surface statistical properties of the text: sentence-length standard deviation, type-token ratio (vocabulary diversity), punctuation density, average word length.
- **Why it differs:** These are structural/measurable properties, not semantic ones. AI text tends toward statistical uniformity (similar sentence lengths, moderate/predictable vocabulary, sparse punctuation variety) because it's optimized for fluency and coherence rather than the irregular, idiosyncratic rhythm of human writing.
- **Blind spot:** It cannot detect meaning, factual coherence, or context — a human who writes in short, uniform sentences (e.g., a non-native speaker, a technical style guide, a child) will score as "AI" on this signal alone, and an AI prompted to "write with varied sentence length and personality" can trivially defeat every metric here.
- **Output shape:** `{"prediction": "human"|"ai", "confidence": float 0.0-1.0, "metrics": {sentence_length_std_dev, type_token_ratio, punctuation_density, avg_word_length}, "reasoning": str}`

**Combination:** Each signal's `(prediction, confidence)` is converted to a "probability of human" `p_human`:
```
p_human = confidence        if prediction == "human"
p_human = 1 - confidence    if prediction == "ai"
```
Combined score: `combined = 0.60 * llm_p_human + 0.40 * stylometric_p_human`

The LLM signal is weighted higher (60/40) because it captures semantic properties the heuristics structurally cannot, but the heuristic signal still meaningfully pulls the score when the two disagree — this is what makes the combination genuinely two-signal rather than LLM-with-a-footnote.

## 2. Uncertainty Representation

`combined` is a continuous value in `[0, 1]` representing **estimated probability the text is human-written**, not a binary flip.

- **0.60 is not "60% confident AI is right"** — it means: after weighting both signals, the system estimates a 60% chance the text is human-written and a 40% chance it's AI-generated. It is a calibrated-in-spirit estimate, not a guarantee — both signals can be wrong in the same direction (e.g., both penalize plain, uniform human writing), so the score is a *signal-weighted estimate*, not ground truth.

**Thresholds (symmetric 3-band):**

| `combined` range | Label band       |
|-------------------|-------------------|
| 0.00 – 0.40        | Likely AI-generated |
| 0.40 – 0.60        | Uncertain            |
| 0.60 – 1.00        | Likely human-written |

The 0.40–0.60 band exists specifically so the system never forces a confident-sounding label out of a near-coin-flip score — a 0.52 and a 0.58 both land in "Uncertain," which is the honest description of what the system actually knows at that point.

## 3. Transparency Label Design

- **High-confidence AI** (`combined <= 0.40`, i.e. `p_ai >= 0.60`):
  > "This text is likely AI-generated (confidence: {p_ai:.0%}). This assessment is based on automated signals and may be incorrect — see our appeals process if you believe this is wrong."

- **High-confidence human** (`combined >= 0.60`):
  > "This text is likely human-written (confidence: {combined:.0%}). This assessment is based on automated signals and may be incorrect."

- **Uncertain** (`0.40 < combined < 0.60`):
  > "This text's origin could not be reliably determined (confidence: {combined:.0%}). Automated signals were inconclusive — treat this result as inconclusive, not as evidence of AI use."

All three variants always disclose that the result comes from automated signals and can be wrong — the "Uncertain" label is worded to actively discourage anyone from treating it as a soft accusation.

## 4. Appeals Workflow

- **Who can appeal:** Anyone who received a submission result. `/submit` requires a `contact` field (email); this is stored with the submission so a reviewer can follow up, and appeals must reference a valid `submission_id`.
- **What they provide:** `submission_id`, `contact` (must match or supplement the original), and a free-text `reason` explaining why the label is disputed.
- **What happens on appeal:**
  1. System looks up the submission by `submission_id`. If not found → 404.
  2. Submission status is set to `appeal_pending`. The original label and confidence score are **not** hidden or changed — they remain visible, now annotated as under dispute.
  3. An audit log entry is written: `{event: "appeal_filed", submission_id, contact, reason, timestamp}`.
  4. Response confirms receipt: `{status: "appeal_pending", submission_id, message: "Your appeal has been received and will be reviewed."}`.
- **Reviewer queue (`GET /appeals`):** A human reviewer sees a list of all submissions with `status == "appeal_pending"`, each showing: original text snippet, original label, confidence, both signals' individual outputs, the appeal reason, and contact. The reviewer resolves via `POST /appeals/{submission_id}/resolve` with `{decision: "upheld"|"overturned", notes}`, which updates status to `resolved_upheld` or `resolved_overturned` and logs the resolution with timestamp and notes.

## 5. Anticipated Edge Cases

1. **Short, plain-vocabulary creative writing (e.g., children's poetry or a nursery-rhyme-style poem).** Heavy repetition and simple, low-diversity vocabulary by design will score low on type-token ratio and sentence-length variance — both stylometric sub-scores that the heuristic signal reads as "typical of AI." A human-written poem using deliberate repetition for effect can be mislabeled "Likely AI-generated" even though the LLM signal alone might correctly read it as human.

2. **Non-native-English professional or technical writing.** Writers who learned English as a second language often produce grammatically correct, evenly-paced, low-punctuation-variety prose (short declarative sentences, minimal semicolons/dashes) because that's a common ESL writing strategy — this pattern overlaps heavily with what both signals treat as "AI-like." This is a fairness-relevant blind spot: the system risks systematically flagging non-native speakers' authentic work more often than native speakers' work.

(Both cases should be called out explicitly in the transparency label's disclaimer text and considered before this tool is used for any high-stakes/punitive decision.)

## Architecture

### Submission flow
```
Client
  │  POST /submit { text, contact }
  ▼
Flask app (app.py)
  │  raw text
  ▼
Signal 1: Groq LLM classifier ──► {prediction, confidence, reasoning}
  │
  │  raw text (independently, in parallel/sequence)
  ▼
Signal 2: Stylometric heuristics ──► {prediction, confidence, metrics}
  │
  │  both signal outputs
  ▼
Confidence scoring (detector.py: analyze_text)
  │  combined = 0.60*llm_p_human + 0.40*stylometric_p_human
  ▼
Transparency label generator
  │  label text + band (AI/Uncertain/Human) + combined score
  ▼
Audit log (audit.py → SQLite)
  │  submission_id, timestamp, text snippet, signals, label, status=submitted
  ▼
Response to client
  { submission_id, prediction, confidence, label, signals[], text_length }
```

### Appeal flow
```
Client
  │  POST /appeal { submission_id, contact, reason }
  ▼
Flask app
  │  lookup submission_id
  ▼
Status update: submitted → appeal_pending
  │  (label/confidence unchanged, flagged as disputed)
  ▼
Audit log
  │  event=appeal_filed, submission_id, contact, reason, timestamp
  ▼
Response to client
  { status: "appeal_pending", submission_id, message }

  ... later, human reviewer ...

GET /appeals  ──► list of all appeal_pending submissions (full signal detail + reason)
  │
POST /appeals/{id}/resolve { decision, notes }
  ▼
Status update: appeal_pending → resolved_upheld | resolved_overturned
  ▼
Audit log: event=appeal_resolved, decision, notes, timestamp
```

A submitted text always passes through **both** signals independently before scoring — neither signal short-circuits the other — so the combined score always reflects two genuinely distinct measurements. An appeal never mutates the original signal outputs or label; it only adds status and a parallel audit trail, so the original automated assessment remains fully reconstructable even after a human overturns it.

## API Surface (Contract)

| Endpoint | Method | Request body | Response |
|---|---|---|---|
| `/submit` | POST | `{text, contact}` | `{submission_id, prediction, confidence, label, signals[], text_length}` |
| `/appeal` | POST | `{submission_id, contact, reason}` | `{status, submission_id, message}` |
| `/appeals` | GET | — | `{count, entries: [{submission_id, text_snippet, label, confidence, signals, reason, contact}]}` |
| `/appeals/{id}/resolve` | POST | `{decision, notes}` | `{submission_id, status, resolved_at}` |
| `/logs` | GET | — | `{count, entries[]}` (existing) |
| `/health` | GET | — | `{status: "ok"}` (existing) |

## AI Tool Plan

**M3 — Submission endpoint + first signal**
- **Spec sections provided to AI tool:** Detection Signals §1 (Signal 1 only) + Architecture diagram (submission flow) + API Surface row for `/submit`.
- **What I'll ask for:** A Flask app skeleton with a `/submit` route accepting `{text, contact}`, plus the `_groq_signal` function implementing Signal 1's exact output shape.
- **Verification:** Call `_groq_signal` directly from a Python shell on 3 inputs — an obviously AI-generated paragraph, an obviously human one, and a short ambiguous one — and confirm the prediction/confidence/reasoning fields are populated and sane, *before* wiring it into the endpoint.

**M4 — Second signal + confidence scoring**
- **Spec sections provided:** Detection Signals §1 (both signals) + Uncertainty Representation §2 + Architecture diagram.
- **What I'll ask for:** The `_stylometric_signal` function and the `analyze_text` ensemble function implementing the 0.60/0.40 weighting and the 3-band thresholds.
- **Verification:** Run both signals + the combiner on the same 3 test inputs from M3 and confirm: (a) scores differ meaningfully between the clearly-AI and clearly-human samples (not clustered near 0.5), and (b) the ambiguous sample lands in the 0.40–0.60 "Uncertain" band rather than being forced to a side.

**M5 — Production layer (labels + appeals)**
- **Spec sections provided:** Transparency Label Design §3 + Appeals Workflow §4 + Architecture diagram (appeal flow) + API Surface rows for `/appeal`, `/appeals`, `/appeals/{id}/resolve`.
- **What I'll ask for:** The label-generation function (mapping `combined` + band to exact label text from §3) and the `/appeal`, `/appeals`, `/appeals/{id}/resolve` endpoints with SQLite status tracking.
- **Verification:** Manually submit texts engineered to land in each of the 3 confidence bands and confirm the exact label text matches §3 for all three; then file an appeal against one submission and confirm its status flips to `appeal_pending` in `/appeals`, and that resolving it updates status and is reflected in the audit log.
