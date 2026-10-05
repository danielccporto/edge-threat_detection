# Decision Log (ADR-lite)

Chronological record of project decisions and their reasoning. Feeds the
writeup required in the deliverable ("reasoning for each task").

---

## D1 — Organize data into `data/raw/` (immutable) + `data/interim/` (derived)
**Context:** loose CSVs sitting at the repo root. **Decision:** consolidate
everything under `data/`, with `raw/` versioned and immutable and `interim/` for
derived artifacts (gitignored).
**Why:** separates the source of truth from reproducible artifacts; standard
data-project layout.

## D2 — Standardization layer BEFORE the join
**Context:** every type comes in as a string from the CSV, and the time column
names are inconsistent across tables. **Decision:** create `src/ingestion` with
typed casting + contract validation before any join.
**Why:** prevents silent type/format bugs from propagating into 2.1-2.4; fails
early and loudly if the contract breaks.

## D3 — LIGHT name standardization
**Decision:** keep the original names from the prompt; standardize only the time
columns (`timestamp→event_ts`, `active_from→active_from_ts`, etc.).
**Alternatives:** keep everything as-is (lives with the inconsistency) / rename
everything (drifts away from the prompt). **Why:** a balance between cleanliness
and fidelity.

## D4 — Intermediate output in Parquet
**Decision:** `data/interim/*.parquet`. **Main reason:** it preserves the typing
(UTC datetime, int, ordered categorical) — CSV would turn everything back into
strings. Secondary: columnar/compressed, idiomatic in the ML ecosystem, and
scales to the case's production volume. **Accepted tradeoff:** parquet is not
hand-inspectable → which is why `raw/` stays as readable CSV.

## D5 — Prediction unit: per-request with source features
**Decision:** the model decides per request (fits the edge's <5ms budget), but
uses aggregated IP/JA3/session features; the label is propagated from the
source+window down to the request. **Alternatives:** per-source (drifts away
from the edge's blocking unit) / both. **Why:** reconciles the edge constraint
with the fact that the attack signal emerges across a sequence; connects to 3.1
(state on a stateless edge).

## D6 — Strict temporal join (2.1)
**Decision:** a request is malicious only if it matches (ip/CIDR/JA3) **and**
falls within `[active_from, active_until]`. Multiple matches → class by highest
confidence (tie-broken by severity). **Why:** respecting the temporal bounds
avoids labeling a source's activity as malicious when it falls outside the
incident window.

### Findings from 2.1 (recorded in reports/2_1_labeling_report.md)
- 592 malicious (1.18%) / 83:1 imbalance in the sample (production <0.1%).
- 36 "no-match" incidents investigated → they are **redundant** labels (the
  source is already covered by another incident at the real time); gray zone = 0.
- 24/33 IPs have multiple incidents (one with 19) → imprecise forensic windows;
  deduplicate by source before any source-level analysis.
- Positive-Unlabeled nature: "benign" = unlabeled, not clean.

## D7 — Temporal split, imbalance handled only on the train fold (planned for 2.3)
**Decision:** separate train/test by time (no leakage); handle the imbalance
(class weights / sampling) **only on the train fold**, never before the split.
**Why:** resampling before the split leaks information and inflates the metric;
the temporal split simulates the real drift scenario.

---

## D8 — Source features via causal rolling windows, dual window (2.2)
**Decision:** for each request, aggregate only the **prior (causal)** requests
from the same source over **two windows**: temporal (**5 min**) and count-based
(**last 20 requests**). The window sizes are left as hyperparameters.
**Discarded alternatives:** global per-source aggregate (leaks the future,
unusable in real time) and session-by-gap (complex to serve at the edge) — both
become mentions in the writeup.
**Why:** it is the only option that (1) does not leak the future into 2.3's
temporal split, (2) is computable at the edge in real time with lightweight
per-source state (the basis for 3.1), (3) captures both bursts (5 min) and
low-and-slow behavior (20 req).

## D9 — Headers via flags + counts (2.2)
**Decision (default):** derive per-request flags/counts
(`has_cookie`, `has_authorization`, `has_referer`, `n_headers`,
`has_content_type`). Do not one-hot the full set of values (high cardinality and
little signal). **Why:** lightweight, interpretable, and cheap at the edge.

## D10 — Models: LightGBM (primary) + Logistic Regression (baseline/edge)
**Decision:** shallow LightGBM as the primary model (accuracy, feature
importance, calibration) and LogReg as the edge-deployable floor and
distillation target (2.4). Random Forest and a single tree remain mentions.
**Why:** latency is not the bottleneck (everything is <5ms); the criteria are
size/WASM + calibration, where a shallow GBDT dominates on accuracy-per-byte and
LR is the minimal servable option.

## D11 — Imbalance: class weights + threshold calibration (SMOTE for comparison only)
**Decision:** keep the real distribution; handle the imbalance with
`scale_pos_weight`/`class_weight='balanced'` **only on the train fold** + a
threshold choice from the PR/cost curve (3.3). SMOTE/oversampling only as a
comparison experiment in the writeup. **Why:** the bias toward benign is a
THRESHOLD problem, not a learning one (separation is already extremely high);
SMOTE fabricates unrealistic combinations in the sequence features, hurts
precision, and breaks calibration.

## D12 — Exclude raw IDENTITY features; country in an A/B test
**Decision:** a model with a **behavioral/aggregated** core, WITHOUT raw
`source_ip`, `tls_fingerprint` (JA3), or `country` as predictors. Train two
versions (with and without `country`) to **quantify the leakage**. Identity
enters only as (a) derived behavior (which we already have: src_*), (b) client
class, (c) reputation/threat-intel as a SEPARATE signal (a boolean known_bad),
not as a category the model memorizes.
**Evidence (data):** JA3 and country are near-lookups of the label (5 JA3 = 100%
malicious, 4 = 0%; RU/CN/VN/ID = 100%); the label was created from identity in
the first place (circular); 0/30 malicious IPs in the test are new → a metric
based on identity would be unrealistic memorization and is exactly the
adversarial collapse in 3.4.

## D13 — Temporal split: cut on day 11 (~72/28) + walk-forward
**Decision (confirmed):** headline split = train **Jan 06-10**, test
**Jan 11-12** (no shuffle; preprocessing fit only on the train set) +
**walk-forward (TimeSeriesSplit)** as a robustness/variance validation.

**Key reasoning (important):** the attacks are **localized in time** — each type
occurs only on specific days:
`scanner`→07; `credential_stuffing`→07 and 11; `api_abuse`→08-09; `ddos_l7`→09
and 12; `zero_day_exploit`→**day 10 only (6 cases)**; day 06 = 100% benign.
Consequence: **no single cut covers every type in both train AND test** — which
defines the trade-off of where to cut:
- cut at 10 (~60/40): the test includes the never-seen `zero_day` → measures a
  NEW attack, but n=6 and less training data.
- **cut at 11 (~72/28): test = cred_stuffing + ddos (already-seen types), ~240
  positives → a stable, fair score.** ← chosen as the headline.
- cut at 12 (~87/13): test is `ddos` only, 101 positives → narrow/unstable.

Walk-forward recovers what the single cut loses: each type (scanner, api_abuse,
zero_day) lands in the test on some fold, and we report variance instead of a
lucky number. Day 06 stays in training (it anchors "normal"); recall on zero_day
(day 10) is reported separately as a novel-attack probe.

## D14 — Critical validation revealed limits; the final model is HYBRID
**Context:** the validation battery (`src/modeling/validate.py`,
reports/2_3_validation.md) showed: (T1) a 1-line rule nearly ties LGBM → the
synthetic test is trivially separable; (T2) label-shuffle → the pipeline has no
bug; (T3) new source R≈0.76 → the behavioral signal generalizes; (T4) the
**supervised model is blind to a new attack** (recall≈0 on an unseen class).
**Decision:** the final model is NOT supervised-only — it is **hybrid**
(`src/modeling/hybrid.py`): LightGBM (known attacks) **OR** IsolationForest
trained only on benign traffic (anomaly/novel attack). This closes the T4 gap
and delivers what 3.2 asks for.
**Result (leave-one-class-out, recall on the unseen class):** supervised→hybrid:
cred_stuffing 0→0.98; ddos 0.05→0.88; scanner 0→0.92; zero_day 0.33→0.83.
**Honest exception:** `api_abuse` stays at 0 (it mimics legitimate traffic → it
is neither anomalous nor known); this is the low-and-slow/mimicry case, left as
future work (longer session features). Cost: the anomaly layer is budgeted at
~1% FPR; the final operating point is cost-calibrated in 3.3.

## D15 — Hyperparameters via a lightweight, edge-oriented search
**Decision:** don't chase the metric (the task is saturated); instead pick the
**smallest model** that holds the honest performance. Search a small grid via
TimeSeriesSplit on the train set (no leakage), metric = mean PR-AUC
(`src/modeling/tune.py`, reports/2_3_tuning.md).
**Chosen:** LightGBM `n_estimators=120, max_depth=6, num_leaves=15, lr=0.1`
(size-proxy 1800; CV PR-AUC ~0.85 — well below the headline 1.0, confirming how
trivial the test is). There is an even smaller option (leaves=7, size 840, PR-AUC
~0.83) kept for the edge tradeoff in 2.4. IsolationForest is fixed at
n_estimators=200. Thresholds are NOT tuned here — they come from the cost
calibration (3.3).

## D16 — Edge feasibility: the model is not the bottleneck; export to pure JS (2.4)
**Measurements** (`src/deploy/benchmark.py`, reports/2_4_edge.md + 2_4_benchmark.json):
single-sample latency in Python is a misleading ceiling (interpreter overhead);
batch throughput reveals the real cost of LightGBM's arithmetic at **~2µs/req**
(538k req/s), 2,500× under the 5ms budget. Size: LGBM 213KB, LogReg 6KB.
**Export decision:** compile the model to **dependency-free code** via `m2cgen`
(`src/deploy/export_edge.py` → `models/edge/edge_model.js`, 259KB of pure
if-else + `feature_order.json`). Serving: the Worker computes per-request
features inline + reads the source's rolling state (KV/Durable Object, the
critical path — 3.1) + scoreRequest + anomaly + OR decision; a model update =
publishing a new artifact (central retraining, ties into drift/3.2). **The real
bottleneck = source-feature state (3.1) + threshold calibration (3.3), not
inference.** Final model = **hybrid LightGBM + IsolationForest** (LogReg does NOT
ship; it appears only as a scale reference). Since the measurements leave an
enormous margin, **no simplification is necessary**; contingencies on record: a
~2× smaller LGBM variant (preferred) or a statistical score in place of
IsolationForest.

---
# Part 3 — Deep-dives (writeups in reports/3_x_*.md)

## D17 — State at the edge: aggregate + Durable Objects + graceful degradation (3.1)
**Verdict** (reports/3_1_stateful_edge.md): keeping session context on a
stateless edge is feasible by storing **per-source aggregated state**
(EWMA/ring buffer/HLL, ~hundreds of bytes, O(1) update), with **sticky routing
by key → a single Durable Object per source**, a local PoP cache, and
**write-behind**. The budget bottleneck = **a single state read (~ms)**; the
model at ~2µs is negligible. If the store goes down: **graceful degradation** —
a fallback model with per-request features only (the feature separation already
enables this), local anomaly/reputation, and **fail-open on payment flows**
(FPs are expensive) with coarse rate-limiting.

## D18 — Cost-based, dynamic, calibrated threshold (3.3)
**Verdict** (reports/3_3_threshold_economics.md): the optimal threshold is not a
fixed number, it is `q* = C_FP/(C_FP+C_FN)` over the **calibrated** probability.
Baseline (FP $2.50 / FN $0.10) → **q*=0.962** (block only at ~96% certainty; FP
is 25× FN; the ML upside is only ~$5k/day → the focus is on not generating FPs).
Campaign (FN $5.00) → **q*=0.333** (aggressive; upside ~$250k/day). Requires
calibration (Platt/isotonic) + a **dynamic threshold by regime** (switch C_FN
when a campaign is detected) + **conditioning on the endpoint** ($2.50 only
applies at checkout). The cost values are from the prompt; the math and
conclusions are ours.
