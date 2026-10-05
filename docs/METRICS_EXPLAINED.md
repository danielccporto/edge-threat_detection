# The Metrics Explained in Plain Language

> Picture our model as a **gatekeeper** at a front desk. For every person who
> arrives (each request), it decides: **let them in** (benign) or **turn them
> away** (attack). All the metrics below measure how good that gatekeeper is.
>
> At each point, the **`In the project →`** line connects the explanation to the
> model, the technique, and the file where the decision was made/found.

## The three "gatekeepers" we use (spec sheet)

| Nickname | Real model | How it learns | Role |
|---|---|---|---|
| Smart gatekeeper | **LightGBM** (boosted forest of trees) | with answer keys (supervised) | starter — known attacks |
| Simple gatekeeper | **Logistic Regression** | with answer keys (supervised) | lightweight floor for tight environments |
| Anomaly gatekeeper | **IsolationForest** | from normal traffic only (unsupervised) | sniffs out the unseen |

Where each stage lives: `src/modeling/` (`split.py`, `preprocess.py`, `tune.py`,
`train.py`, `evaluate.py`, `validate.py`, `hybrid.py`) and the results in
`reports/` (`2_3_model_report.md`, `2_3_tuning.md`, `2_3_validation.md`,
`2_3_hybrid.md`).

## The vocabulary (the gatekeeper's "scoreboard")

- **Capture rate (recall):** of all the *real* attackers, how many did it turn
  away? Recall 0.90 = it catches 90 out of every 100.
- **Precision (precision):** of everyone it turned away, how many were *actually*
  attackers? Precision 0.70 = 30% of those turned away were innocent.
- **False positive rate (FPR):** of all the innocent visitors, how many were
  turned away by mistake? This is the "collateral damage" — very expensive here
  (blocking a payment = a loss).
- **The seesaw:** these numbers fight each other. A paranoid gatekeeper turns
  everyone away; a relaxed one turns away no one. There is no "perfect" — there
  is **choosing the balance**.
- **The overall grade (PR-AUC):** a 0-to-1 score that sums up the gatekeeper
  across every level of strictness. We use **PR-AUC** (fair when attackers are
  rare); ROC-AUC gives a **falsely high** grade in this scenario.

---

## What each result told us

**1) The near-perfect grade wasn't a celebration — it was a red flag.**
A gatekeeper that seems to score 100% is usually either in an easy line or
cheating.
> `In the project →` the one that scored ~perfectly (PR-AUC 1.0) was the
> **LightGBM**, on the **temporal-separation test** (trains on days 06–10,
> tested on days 11–12). Found by running `train.py` →
> `reports/2_3_model_report.md`. That gatekeeper's hyperparameters (number of
> trees=120, depth=6, leaves=15) were chosen by a **lightweight search** in
> `tune.py` (see the section on size).

**2) A silly rule tied the smart gatekeeper.**
A one-line little rule ("if they keep hitting the same door, turn them away")
scored almost as well as the model → **the test attacks are too obvious**.
> `In the project →` technique: compare the **LightGBM** against a **trivial
> baseline** (the rule `address_diversity ≤ 2`). Done in **Test 1** of
> `validate.py` → `reports/2_3_validation.md`. The rule got F1 0.96; the model,
> 0.98.

**3) The honest grade is ~0.92, not 1.0.**
Testing across **several different weeks** and averaging, the real grade showed
up.
> `In the project →` technique: **walk-forward** (validation that slides over
> time, `TimeSeriesSplit` with 4 slices), applied to the **LightGBM**. In
> `train.py` → report. It gave PR-AUC 0.92 ± 0.08 (the ± spread shows it does
> worse in some weeks).

**4) It was "cheating" off the badge.**
A few fields (the origin address and the arriving party's "fingerprint") almost
gave away the answer — memorizing names instead of observing behavior.
> `In the project →` technique: a **feature A/B test** (train with and without
> the `country` field) + an analysis that showed those fields acting as "almost
> the answer key". Measured in `train.py` (with/without country comparison) and
> analyzed before decision **D12** (`docs/DECISIONS.md`). Effect: for the
> **LightGBM** nothing changed (it doesn't need the crutch); for the **Logistic
> Regression** it improved by 10 points (it was leaning on it). Conclusion: we
> **ban** the raw identity fields as a clue.

**5) The smart gatekeeper is much better than the simple one.**
Catching these attacks requires **combining several clues at once** — the simple
one doesn't do that.
> `In the project →` a direct **LightGBM × Logistic Regression** comparison in
> the same results table (`train.py` → report): F1 0.98 vs 0.67. Each with its
> own data preparation (`preprocess.py`). Recorded in decision **D10**.

**6) It is cautious: it almost never blocks an innocent, but lets some through.**
It makes very few mistakes against innocents, but ~4% of known attackers slip
past.
> `In the project →` this is the effect of the chosen **threshold**: we take the
> value that maximizes the balance **on the train set** and apply it on the test
> (function `best_f1_threshold` in `evaluate.py`). LightGBM result: precision
> 1.0, capture 0.96, false positive rate 0.0.

**7) We proved there's no cheating in the code.**
We shuffled the answer key on purpose; if it still "got it right", there would be
leakage. It started getting everything wrong — exactly as expected.
> `In the project →` technique: a **label-shuffle test** on the **LightGBM**.
> **Test 2** of `validate.py`. The grade collapsed to ~0.01 → **clean
> pipeline**.

**8) It watches behavior, it doesn't memorize faces.**
With people it had never seen, it kept doing well.
> `In the project →` technique: **source separation** (ensuring no training IP
> appears in the test). **Test 3** of `validate.py`. Capture only dropped from
> 0.95 to ~0.75 → the **LightGBM** judges by *how they behave*. Reinforces
> decision D12.

**9) The critical weak spot: it doesn't recognize a novel attack.**
Hiding an entire attack type from training, on the test it caught almost none.
> `In the project →` technique: **hide one attack class at a time**
> (leave-one-class-out) on the **LightGBM**. **Test 4** of `validate.py`. Capture
> ≈0 on almost all of them → the supervised model alone is insufficient. It was
> this result that **motivated changing the architecture** (decision D14).

**10) The solution: a second gatekeeper that flags the unusual.**
It doesn't study criminals — it learns only *normal* behavior and alarms on the
odd, even when novel. Final rule: block if the first one recognizes OR the second
one finds it unusual.
> `In the project →` model: **IsolationForest** (200 trees), trained **on benign
> traffic only**, with the alarm tuned to bother at most 1% of innocents (99th
> percentile of "unusualness"). Combined with the LightGBM via a **logical OR**
> in `hybrid.py` → `reports/2_3_hybrid.md` (decision D14). The capture of novel
> attacks jumped from ~0% to 67–98%, at the cost of ~0.6% false positives.

**11) One attack still escapes both.**
The one that **pretends to be a legitimate user** (slow, error-free) is not
recognized by the first (it's new) nor flagged by the second (it looks normal).
> `In the project →` this is the `api_abuse` class, seen in the same hybrid test
> (`hybrid.py`): capture 0.00 even with both gatekeepers. Mapped as future work
> (longer session features), connects to Part 3.4.

---

## On the size of the smart gatekeeper (hyperparameters)

We didn't pick "the strongest", but **the smallest one that doesn't lose
performance** — because it has to fit in a tight environment (the edge).
> `In the project →` technique: a **lightweight search** testing size
> combinations under a temporal validation, in `tune.py` →
> `reports/2_3_tuning.md` (decision D15). Chosen: 120 trees, depth 6, 15 leaves.
> We also keep a ~2× smaller version (only 2% worse) as an ace up our sleeve for
> the edge stage (2.4).

## In one sentence

We have a **smart gatekeeper (LightGBM) that is cautious and competent against
known threats**, reinforced by an **anomaly gatekeeper (IsolationForest) that
sniffs out the unseen**, validated by a battery of tests (`validate.py`) that
separated "genuinely good" from "good by luck/bug" — with one clear limit (the
disguised attack) and a balance point still to be dialed in according to the cost
of each error.
