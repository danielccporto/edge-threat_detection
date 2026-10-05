# Part 1 — End-to-End Design

How to design, train, and deploy an ML system to detect malicious HTTP traffic at
the edge. This is the full process view; the details and numbers for each stage
are in the referenced reports (2.x and 3.x).

---

## 0. Explicit assumptions (where the brief is ambiguous)
- **Decision unit = request**, enriched with source context. It fits the edge's
  real-time blocking without giving up the sequence signal.
- **"Benign" = unlabeled**, not "proven clean" (Positive-Unlabeled).
- **Real prevalence <0.1%** (the sample has 1.18% due to synthetic amplification);
  calibration assumes the production prevalence.
- **Threat-intel feed** covers ~30% of attacks (it did not come as data) → it
  enters as a **reputation** feature, a separate signal that degrades gracefully.
- **Cost:** FP on payment = $2.50; FN = $0.10 (values from the brief, 3.3).
- **Runtime:** Cloudflare Workers / WASM, no GPU, with KV/Durable Objects for state.

## 1. Data handling
Three sources: request log (fact), headers (1:N), and incident labels
(per source + window). Pipeline:
1. **Standardization/ingestion** (`src/ingestion`): typed casting + a validated
   schema contract (PK, nulls, domains), output in Parquet. Fails early if the
   contract breaks.
2. **Labeling via temporal join** (`src/labeling`, 2.1): a request is malicious
   if it matches (exact IP / CIDR / JA3) **and** falls within
   `[active_from, active_until]`. Result: 592 positives (1.18%), 83:1 imbalance.
   Gaps documented (redundant incidents, gray zone = 0, PU nature).

**Production assumption:** the threat-intel feed is joined as enrichment
(IP/ASN/JA3 reputation), not as a label.

## 2. Feature engineering (2.2)
Two families (`src/features`):
- **Per-request** (stateless, computable on an isolated edge): path, status/error,
  body/latency, method, non-browser user-agent, headers (flags/counts).
- **Source-level — rolling CAUSAL** (5min + 20-req windows): rate, error rate,
  endpoint/status diversity, timing regularity. Past only → no leakage and
  servable in real time.
- **Reputation** (threat-intel): a separate `known_bad` boolean.

Critical decision: **raw identity (IP/JA3/country) left out** — it is a near-lookup
of the label and collapses under rotation (3.4). The identity signal enters as
*derived behavior*, not as the memorizable identifier. The highest-power features
are the behavioral source-level ones (error rate, endpoint diversity).

## 3. Model selection (2.3 + 3.2)
**Two-layer hybrid architecture:**
- **Supervised — LightGBM** (shallow, 120 trees): precise on known attacks; small
  and fast for the edge; calibratable probabilities.
- **Unsupervised — IsolationForest** (trained on benign only): a safety net for
  **novel** attacks — closes the supervised blind spot proven in leave-one-class-out.
- **Decision = OR** (supervised recognizes **or** anomaly fires).
- Imbalance handled via `class_weight` at training only; probability
  **calibrated** (Platt/isotonic) so the cost-based threshold makes sense.
- Logistic Regression stays as a reference/distillation target, not in production.

## 4. Training methodology (2.3 + validation)
- **Temporal split** (train on the past, test on the future) + **walk-forward**
  for variance; never shuffle time.
- **Preprocessing inside the Pipeline**, fit on training only (no leakage).
- **Critical validation battery** (`src/modeling/validate.py`): label-shuffle
  (clean pipeline), trivial baseline (synthetic data is easy → honest metric via
  walk-forward ~0.92), split by source (generalizes by behavior),
  leave-one-class-out (supervised blind to novel attacks → motivates the hybrid).
- **Hyperparameters** via a lean, edge-oriented search: the smallest model that
  keeps performance (D15).

## 5. Edge deployment strategy (2.4 + 3.1)
- **Model compiled** to dependency-free code (`m2cgen` → JS/WASM); the arithmetic
  costs ~2µs/req (2,500× under the 5ms budget). The model is not the bottleneck.
- **Session state** (3.1): state **aggregated per source** (EWMA/ring buffer/HLL)
  in a **Durable Object** with sticky key-based routing + local PoP cache +
  write-behind. The hot path is dominated by **1 state read**.
- **Cost-based threshold** (3.3): `q* = C_FP/(C_FP+C_FN)` over the calibrated
  probability — ~0.96 at baseline, ~0.33 during a campaign. **Dynamic** (switches
  by regime) and **endpoint-conditional** (checkout is extra-conservative).
- **Graceful degradation:** if state goes down, fall back to the per-request model
  + anomaly/reputation, with fail-open on payment flows.
- **Model update** = publish a new compiled artifact (canary/shadow deploy); no
  call to a central server on the hot path.

## 6. Production monitoring (3.2 + 3.4)
- **Drift:** monitor the feature distribution shift and the **anomaly rate**; a
  spike signals a new pattern → alert + possible campaign mode + retraining.
- **Label loop:** 3 sources with distinct confidence (instant high-precision WAF
  triggers; delayed high-quality forensics; red team). **Active learning**
  prioritizes the anomalies not recognized by the supervised model; **weak/
  pseudo-labels** enable earlier retraining.
- **Short retraining cadence** (weekly drift) with temporal validation before
  promoting.
- **Adversarial robustness:** variability meta-features (JA3/timing churn) make
  evasion self-incriminating; continuous red-teaming feeds back into training;
  anchor features in the **attack's objective** (expensive to fake).
- **Business metrics:** track the **cost** (FP/FN in $) and the block rate on
  payment flows, not just precision/recall.

## Closing
The system is a **cost-calibrated hybrid detector**, served compiled at the edge
with state aggregated per source, evaluated rigorously (validation that separated
signal from artifact), with known limits (`api_abuse`/mimicry) and a retraining
cycle that closes the labeling gap. Every piece was decided by evidence (metrics
and tests), documented in `docs/DECISIONS.md` (D1–D18).
