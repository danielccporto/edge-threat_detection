# CloudWalk — Malicious Traffic Detection at the Edge

An ML system that classifies HTTP requests as malicious/benign in real time at
the **edge** (CDN/WAF), under 5ms/req, with no GPU and a constrained runtime (WASM).
Response to the *ML Engineer – Edge Security Assessment*.

**Final model:** a two-layer hybrid — **LightGBM** (known attacks) +
**IsolationForest** (anomaly layer, covers novel attacks), with an OR decision and
a **cost**-calibrated threshold.

---

## Project structure

```
ca_case/
├── data/
│   ├── raw/           # original CSVs (immutable)
│   └── interim/       # typed derivatives in Parquet (generated; gitignored)
├── src/
│   ├── ingestion/     # standardization + schema contract  (standardize, schema)
│   ├── labeling/      # temporal join of labels (2.1)       (join_labels, report)
│   ├── features/      # feature engineering (2.2)            (build_features)
│   ├── modeling/      # split, preprocess, tune, train, evaluate, validate, hybrid (2.3)
│   └── deploy/        # benchmark + export to edge (2.4)    (benchmark, export_edge)
├── models/            # trained models + models/edge/edge_model.js (generated)
├── reports/           # outputs and writeups per task (1_design, 2_x, 3_x, ...)
├── docs/              # understanding, decisions (ADR), and summaries
├── requirements.txt
└── README.md
```

## Setup

Requires **Python 3.11+**.

```bash
python -m venv venv
# Windows:  venv\Scripts\activate     |  Linux/Mac:  source venv/bin/activate
pip install -r requirements.txt
```

## How to run (pipeline, in order)

Each stage reads the output of the previous one. Run from the project root:

```bash
# 1. Standardization: data/raw/*.csv -> data/interim/*.parquet (validates the schema)
python -m src.ingestion.standardize

# 2. Labeling (2.1): temporal join + counts/gaps report
python -m src.labeling.join_labels
python -m src.labeling.report

# 3. Feature engineering (2.2): 35 features -> data/interim/features.parquet
python -m src.features.build_features

# 4. Modeling (2.3)
python -m src.modeling.tune       # (optional) lean hyperparameter search
python -m src.modeling.train      # trains LightGBM + LogReg (with and without country)
python -m src.modeling.validate   # critical validation battery (T1–T4)
python -m src.modeling.hybrid     # hybrid model + leave-one-class-out proof

# 5. Edge (2.4)
python -m src.deploy.benchmark    # latency / throughput / size
python -m src.deploy.export_edge  # compiles the model to pure JS (models/edge/)
```

> `data/interim/`, `models/`, and `venv/` are generated and kept out of git. The
> original CSVs live in `data/raw/`.

## Suggested reading path (for reviewers)

To follow the full development — every stage and the reasoning behind each
decision — read in this order:

1. **Big picture first** → [docs/PROJECT_SUMMARY.md](docs/PROJECT_SUMMARY.md) — a
   narrated, plain-language walkthrough of the whole project (steps 1–8).
   Optional companion: [docs/METRICS_EXPLAINED.md](docs/METRICS_EXPLAINED.md)
   (metrics explained via a simple analogy).
2. **The data** → [docs/DATA_UNDERSTANDING.md](docs/DATA_UNDERSTANDING.md) —
   sources, keys (PK/FK), the join model and labeling gaps.
3. **Part 2, task by task:**
   - 2.1 Labeling → [reports/2_1_labeling_report.md](reports/2_1_labeling_report.md)
   - 2.2 Features → [docs/FEATURES.md](docs/FEATURES.md)
   - 2.3 Baseline → [reports/2_3_model_report.md](reports/2_3_model_report.md),
     then the critical lens that shaped the final model:
     [validation](reports/2_3_validation.md) →
     [hybrid](reports/2_3_hybrid.md) → [tuning](reports/2_3_tuning.md)
   - 2.4 Edge → [reports/2_4_edge.md](reports/2_4_edge.md)
4. **Part 3 (trade-off deep-dives):**
   [3.1 state](reports/3_1_stateful_edge.md) →
   [3.2 labeling gap](reports/3_2_labeling_bottleneck.md) →
   [3.3 threshold economics](reports/3_3_threshold_economics.md) →
   [3.4 adversarial](reports/3_4_adversarial.md)
5. **Synthesis & rationale** → [reports/1_design.md](reports/1_design.md)
   (end-to-end design that ties it all together) and
   [docs/DECISIONS.md](docs/DECISIONS.md) (**the "why" of every choice, D1–D18**,
   in chronological order — best read alongside the stages above).

> Portuguese versions of every writeup are preserved in
> [docs/pt/](docs/pt/) (the project was developed in Portuguese; English is primary).

### Part 3 — where each deep-dive question is answered

Each Part 3 question from the assessment is answered in its own document:

| Assessment question | Answered in |
|---|---|
| **3.1** Stateless Edge, Stateful Signals | [reports/3_1_stateful_edge.md](reports/3_1_stateful_edge.md) |
| **3.2** The Labeling Bottleneck | [reports/3_2_labeling_bottleneck.md](reports/3_2_labeling_bottleneck.md) |
| **3.3** Threshold Economics (with the math) | [reports/3_3_threshold_economics.md](reports/3_3_threshold_economics.md) |
| **3.4** Adversarial Robustness | [reports/3_4_adversarial.md](reports/3_4_adversarial.md) |

Likewise, **Part 2** tasks map to: 2.1 → [reports/2_1_labeling_report.md](reports/2_1_labeling_report.md);
2.2 → [docs/FEATURES.md](docs/FEATURES.md); 2.3 → [reports/2_3_model_report.md](reports/2_3_model_report.md)
(+ validation/hybrid/tuning); 2.4 → [reports/2_4_edge.md](reports/2_4_edge.md). **Part 1** (the main
design question) → [reports/1_design.md](reports/1_design.md).

### Index of writeups

| Document | Contents |
|---|---|
| [reports/1_design.md](reports/1_design.md) | **Part 1** — end-to-end design (data→features→model→deploy→monitoring) |
| [reports/2_1_labeling_report.md](reports/2_1_labeling_report.md) | 2.1 — labeling, counts, gaps |
| [docs/FEATURES.md](docs/FEATURES.md) | 2.2 — feature catalog + predictive power |
| [reports/2_3_model_report.md](reports/2_3_model_report.md) | 2.3 — baseline metrics |
| [reports/2_3_validation.md](reports/2_3_validation.md) | 2.3 — critical validation (why to trust/distrust) |
| [reports/2_3_hybrid.md](reports/2_3_hybrid.md) | 2.3 — hybrid model and proof on a novel attack |
| [reports/2_3_tuning.md](reports/2_3_tuning.md) | 2.3 — edge-oriented tuning |
| [reports/2_4_edge.md](reports/2_4_edge.md) | 2.4 — edge feasibility (latency/memory/export) |
| [reports/3_1_stateful_edge.md](reports/3_1_stateful_edge.md) | 3.1 — state on a stateless edge |
| [reports/3_2_labeling_bottleneck.md](reports/3_2_labeling_bottleneck.md) | 3.2 — labeling gap (supervised ↔ unsupervised) |
| [reports/3_3_threshold_economics.md](reports/3_3_threshold_economics.md) | 3.3 — cost-based threshold (with the math) |
| [reports/3_4_adversarial.md](reports/3_4_adversarial.md) | 3.4 — adversarial robustness |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Decision log (D1–D18) with context and rationale |
| [docs/PROJECT_SUMMARY.md](docs/PROJECT_SUMMARY.md) | Narrated summary of the whole project |
| [docs/METRICS_EXPLAINED.md](docs/METRICS_EXPLAINED.md) | Metrics explained in plain language |
| [docs/DATA_UNDERSTANDING.md](docs/DATA_UNDERSTANDING.md) | Data dictionary + join model |

> Note: the auto-generated numeric reports (`2_1_labeling_report.md`,
> `2_3_model_report.md`, `2_3_validation.md`, `2_3_hybrid.md`, `2_3_tuning.md`)
> remain in Portuguese because they are produced by code.

## Key results (honest)

- Labeling: 592 malicious (1.18%), 83:1 imbalance.
- Baseline (single-split test) looks nearly perfect, **but** this is an artifact of
  trivial synthetic data (a 1-line rule nearly ties it). **Honest metric
  (walk-forward): PR-AUC ~0.92.**
- Supervised alone is **blind to novel attacks** (recall≈0 on an unseen class);
  the **hybrid recovers 4/5 classes** (0.67–0.98). Exception: `api_abuse` (mimicry).
- Edge: ~2µs/req inference (2,500× under the 5ms budget), ~259KB model in pure JS.
- Cost-based threshold: ~96% confidence at baseline, ~33% during an active campaign.

## Main assumptions
Decision unit = request (with source context); "benign" = unlabeled
(Positive-Unlabeled); real prevalence <0.1% (amplified sample); raw identity
(IP/JA3/country) **excluded** from the model due to leakage/robustness; the
threat-intel feed is treated as a reputation feature (it was not provided as data).
Details in [reports/1_design.md](reports/1_design.md) and
[docs/DECISIONS.md](docs/DECISIONS.md).
