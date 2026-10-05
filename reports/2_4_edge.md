# 2.4 — Edge Feasibility

> **Final model = hybrid LightGBM + IsolationForest.** Logistic Regression is
> NOT part of the production solution — it appears here only as a **scale
> reference point** (the linear floor that's achievable), to put the size of the
> models we actually use into context.

## Breaking down the 5ms budget

The critical per-request path at the edge is:
```
per-request features (µs)  +  LOOKUP of source state  +  rolling features (µs)  +  MODEL (µs)
```
**Up-front conclusion:** model inference is the **cheapest** part. The real
budget bottleneck is **computing the source features + reading the state**
(covered in 3.1). Below we prove the model fits with room to spare.

## Measurements (reports/2_4_benchmark.json)

| Model | Size (joblib) | Complexity | 1-req latency (Python) | Batch throughput |
|---|---|---|---|---|
| **LightGBM** (final model) | 213 KB | 120 trees / 3,480 nodes | p50 5.9ms • p99 9.5ms | **538,598 req/s** |
| **IsolationForest** (final model) | — | 200 trees | mean 12.2ms • p99 19.6ms | — |
| Logistic Regression (reference only) | 6 KB | 36 coefficients | p50 4.2ms • p99 7.3ms | 796,752 req/s |

### ⚠️ Reading the numbers correctly
**Single-sample latency in Python is a misleading ceiling** — it measures the
per-call overhead of the interpreter + pandas + sklearn dispatch, **not** the
model's arithmetic. The proof is in the batch throughput: 538k req/s for
LightGBM is equivalent to **~1.9µs per request** once the overhead disappears.
In other words:

- **The real cost of LightGBM arithmetic ≈ 2µs/req** (0.002ms) — 2,500× below
  the 5ms budget.
- In a **compiled** runtime (WASM/JS, no Python) there's no interpreter
  overhead; the prediction is ~720 integer comparisons (depth 6 × 120 trees).
- Logistic Regression is even smaller: a single 36-term dot product.

**Latency verdict:** the supervised model fits within the budget with an
enormous margin. IsolationForest (200 trees) is the heaviest, but still trivial
once compiled; see the simplification below.

### Throughput (50k req/s/node) — what we measured and what depends on 3.1
The measured throughput is **the model's**: ~538k req/s on **a single core**
(Python, batched). A direct calculation against the requirement:
`50,000 req/s × 2µs = 0.1 s of CPU per second = ~10% of a core` just for
inference. In other words, **the model is not the throughput bottleneck** —
there's a large margin, which still scales horizontally (more cores/nodes).

**Honest caveat:** this is throughput *of the model*, single-threaded, not a
**system** load test. At 50k req/s, the real bottleneck is not the model's CPU
but the **source state I/O** (reading/updating the rolling counters on every
request) — which is a state-architecture problem, covered in **3.1**, and was
not measured here because it depends on the real edge runtime and state store.

## Memory / size

- LightGBM: 213 KB serialized; compiled to JS it came out to **259 KB** (pure
  if-else).
- Logistic Regression: 6 KB (essentially just the weights).
- All fit comfortably within a Cloudflare Worker's limit (~1 MB compressed on
  the free plan; 10 MB paid). IsolationForest with 200 trees would add a few
  hundred KB — still feasible, but it's the first candidate to trim.

## Distillation / simplification

**The measurements show we do NOT need to simplify** — the final model fits the
budget with a ~2,500× latency margin and sits a few hundred KB below the limit.
The options below are recorded only as **contingencies**, in case a future
scenario (a tighter runtime, an edge with a lower ceiling) requires trimming:

1. **A ~2× smaller LightGBM variant** (`num_leaves=7`, ~2% less PR-AUC), already
   identified during tuning (reports/2_3_tuning.md) — the preferred path if a
   reduction is needed, since it keeps the same model family.
2. **A lighter anomaly layer:** since IsolationForest (200 trees) is the
   heaviest component, swap it for a statistical score (Mahalanobis distance /
   z-score over the source features) or reduce `n_estimators`.
3. *(Extreme hypothesis)* distill the LightGBM into a 6 KB Logistic Regression —
   listed for completeness, but unlikely given the current margin and the recall
   loss.

## Export and serving at the edge

**Export (done — concrete proof):** we used `m2cgen` to compile the LightGBM
into **dependency-free JavaScript** (`models/edge/edge_model.js`, 259 KB) — a
`scoreRequest(input)` function of pure comparisons, plus
`models/edge/feature_order.json` with the expected order of the 35 features.
Reproducible via `python -m src.deploy.export_edge`.

**Export alternatives:** ONNX + onnxruntime-web (a heavier runtime) or Treelite
(generates C → WASM). The pure m2cgen code is the lightest and has no
dependencies.

**Proposed serving architecture:**
```
Request → Worker (edge)
  1. extract per-request features (inline, stateless)       ~µs
  2. read/update rolling source state in KV/Durable Object  ← critical path (3.1)
  3. scoreRequest(features)  [compiled LightGBM]             ~µs
  4. anomaly (compiled IF or statistical score)             ~µs
  5. OR decision + cost-calibrated threshold (3.3) → allow/throttle/block
```
- **Thresholds and weights** are embedded in the artifact (constants).
- **Updating the model** = publishing a new `edge_model.js` (central retraining
  → deploy to the edge); this fits the drift mitigation (3.2). No call to a
  central server on the hot path (forbidden by the prompt).
- **Source state** is the only stateful component — detailed in 3.1
  (KV/Durable Objects; what breaks if the store goes down).

## Summary
The model **is not the bottleneck**: ~2µs of arithmetic, a few hundred KB,
exportable to pure JS (artifact generated). The real edge challenge is the
**source feature state** (3.1) and the **cost-based threshold calibration**
(3.3), not inference.
