# 3.2 — The Labeling Bottleneck

**Problem:** the best labels arrive 1–3 days after an attack; new patterns can
emerge at any moment. How do we cover the interval between a new attack starting
and us having labeled data for it?

## The proof we already have
Our validation quantified exactly this gap: in the leave-one-class-out run (T4),
the supervised model alone had recall ≈0 on a never-seen class; the **hybrid with
IsolationForest recovered 4 of 5** (0.67–0.98). In other words, this is not
theory — we have already built and measured the answer. Section 3.2 formalizes
*when each model takes the lead*.

## The core idea: who is the "first responder"

```
time →    new attack begins         label arrives (1–3 days)       retraining
          │                          │                              │
UNSUPERV. │■■■■■ covers the unknown ■■■■■                           │ (falls back to the next new one)
SUPERV.   │ (blind to this pattern)       ■■■■ takes over this pattern ■■■■■■■■■■■■→
```

- **Unsupervised (IsolationForest) = first responder.** Needs no label; fires on
  deviation from normal. Covers the **blind window** (day 0 until the label
  arrives). High recall, noisier.
- **Supervised (LightGBM) = specialist.** Precise on what has already been
  labeled. **Takes over the pattern** as soon as it enters the training set.
- **Handoff:** over time, each pattern **migrates from "caught by anomaly" to
  "caught by supervision"**. The anomaly layer is then free to cover the *next*
  unknown.

## Concrete strategy (the label loop)

**1. Label sources, with differing confidence** (the three from the brief):
- **WAF triggers:** high precision, low recall, **instantaneous** → usable right
  away, as weak positive labels.
- **Post-incident forensics:** high quality, **delayed by 1–3 days** → the ground
  truth.
- **Red team:** clean and controlled → excellent for rare classes.

**2. Close the gap faster (active learning):** the anomalies that the
unsupervised layer fires on **and that the supervised model does not recognize**
are the highest-value queue for **prioritized review/labeling**. Rather than
passively waiting out the 1–3 days, we direct human effort at the cases that
matter most.

**3. Provisional labels (weak/pseudo-labeling):** very-high-score anomalies + WAF
triggers become **provisional positive labels** (lower weight) to **retrain
before** forensic confirmation — shrinking the gap from days to hours, taking
care to down-weight them so as not to poison the model.

**4. Short retraining cadence:** since drift is weekly, retrain **frequently**
(daily/weekly) with canary/shadow deploys (remembering that publishing a model to
the edge = publishing a new artifact, D16). This way the supervised model quickly
absorbs what the anomaly layer and the new labels brought in.

**5. Monitor the trigger:** a spike in the **anomaly rate** or a shift in the
feature distribution signals a new pattern underway → alert + possible **campaign
mode** (which also drops the cost threshold, D18) + early retraining.

## When each one "leads" (explicit summary)
| Moment | Primary | Role of the other |
|---|---|---|
| New attack, no label | **Unsupervised** | supervised covers the known ones |
| Weak label (WAF/anomaly) arrives | both; provisional retraining | the handoff begins |
| Confirmed forensic label + retraining | **Supervised** | anomaly goes back to watching the next new one |
| Steady-state regime | Supervised (precision) | anomaly = safety net (recall) |

## Honest limitation
`api_abuse` (low-and-slow mimicry) is the worst case for this gap: it is not
anomalous (it looks legitimate) **and** forensics is slow to spot it → neither the
safety net nor the label arrives quickly. Mitigation: **longer-horizon session
features** and detection via aggregate behavior — future work, the same vector as
3.4.

## Verdict
The labeling gap is resolved through a **division of labor over time**: the
unsupervised anomaly layer is the **immediate safety net** for the unknown; the
supervised model **takes over each pattern** as soon as the label (weak→confirmed)
arrives, accelerated by active learning and frequent retraining. It is the same
hybrid architecture we have already measured — seen here through the lens of
*time* and *label flow*.
