# 3.3 — Threshold Economics (cost-based threshold calibration)

## Assumptions (from the brief)
- Blocking a legitimate request (payment): **C_FP = $2.50**.
- An attack that reaches the origin: **C_FN = $0.10**.
- Volume: **100M req/day**; true prevalence **0.05%** → 50,000 attacks/day,
  99,950,000 benign/day.

## The cost model
Per-request decision: **block** or **let through**. Only two errors carry a cost:
```
Cost(t) = FP(t) · C_FP  +  FN(t) · C_FN
```
(FP = benign requests blocked; FN = attacks that got through.) Correctly blocking
an attack and correctly letting a benign request through cost ~0.

## Optimal threshold (Bayesian decision)
For a request with probability `q = P(malicious)`, we compare the expected cost of
the two actions:
- **Block:** if it is benign (prob. `1−q`) we pay C_FP → expected `(1−q)·C_FP`.
- **Let through:** if it is an attack (prob. `q`) we pay C_FN → expected `q·C_FN`.

Blocking pays off when `(1−q)·C_FP < q·C_FN`, which resolves to:
```
q* = C_FP / (C_FP + C_FN)        (threshold on the calibrated probability)
```

### Baseline
```
q* = 2.50 / (2.50 + 0.10) = 2.50 / 2.60 = 0.962
```
**Only block when you are ~96% sure it is an attack.** Equivalent in precision
terms: the blocked set must have **precision ≥ 0.962** to be profitable (the same
arithmetic seen from the precision side):
```
blocking is worthwhile if  P·C_FN > (1−P)·C_FP  →  P > C_FP/(C_FP+C_FN) = 0.962
```

## Why so conservative? (the daily cost anchors)
- **Block nothing:** 50,000 attacks × $0.10 = **$5,000/day**. This is the ceiling
  on attack losses — low, because attacks are cheap and rare.
- **Block everything:** 99.95M × $2.50 = **~$250 million/day**. Catastrophic.
- Since C_FP is **25× C_FN**, the risk of a wrong block dominates. The maximum
  savings ML can deliver at baseline is only the $5,000/day — so, in a calm
  period, **the model's main job is to NOT produce false positives**, not to
  "catch more".

Example: operating at precision 0.99 and recall 0.90, net savings ≈
`5,000·0.90·(1 − 25·0.01/0.99)` ≈ **$3.4k/day** (out of a $5k ceiling). At
precision 0.962 (breakeven) net savings ≈ 0.

## Active-campaign regime (C_FN = $5.00)
During an active credential stuffing campaign, the cost of letting attacks through
rises to $5.00:
```
q* = 2.50 / (2.50 + 5.00) = 2.50 / 7.50 = 0.333
```
**Now block at just ~33% certainty** (precision ≥ 0.333). The threshold
**collapses** because each missed attack now hurts 50× more than before in
relative terms. And the maximum savings becomes 50,000 × $5.00 = **$250k/day** —
this is where the system "pays its own salary", justifying the acceptance of far
more false positives.

| Regime | C_FN | Threshold q* | Minimum precision | Posture | Max savings/day |
|---|---|---|---|---|---|
| Baseline | $0.10 | **0.962** | 0.962 | very conservative | $5k |
| Campaign | $5.00 | **0.333** | 0.333 | aggressive | $250k |

## Engineering implications
1. **Requires calibrated probability** (Platt/isotonic on top of LightGBM),
   otherwise `q` has no meaning and the threshold becomes a guess.
2. **Regime-dependent dynamic threshold:** detect a campaign (volume/anomaly
   spike) and **switch C_FN** → the threshold drops automatically from 0.962 to
   ~0.33.
3. **Per-endpoint threshold:** C_FP is only $2.50 in the payment flow. On
   revenue-free endpoints the effective C_FP is lower → we can block more
   aggressively there and be extra-conservative at checkout. The threshold should
   be **conditional on the endpoint**, not global.
4. **Consistent with 3.1 (T3):** we saw that the threshold does not transfer
   across populations → per-population + per-regime calibration is part of the
   deploy, not a fixed number.

## Verdict
The threshold **is not a number, it is a function of cost**: `q* =
C_FP/(C_FP+C_FN)`. At baseline, block only at ~96% certainty (FP is 25× more
expensive than FN, and the ML upside is small — the focus is on not creating FPs).
During an active campaign, the threshold drops to ~33% and the upside explodes to
$250k/day. The correct solution is a **dynamic, calibrated threshold, conditional
on regime and endpoint** — not a fixed 0.5.
