# 3.4 — Adversarial Robustness

**Scenario:** the attacker discovers that the model leans heavily on **JA3** and
**timing regularity**, and starts **randomizing the JA3 per request** and **adding
jitter** to the intervals. Recall drops from 92% to 41%. What is the response
plan?

## Starting point: we are already partly shielded
This attack targets a model that *depends* on JA3 and timing — but ours, **by
design, does not**:
- **Raw JA3 was EXCLUDED** as a feature (D12): we proved it was a near-lookup of
  the label and that it would collapse under rotation. Randomizing the fingerprint
  **does not bring down** a model that never used it.
- **Timing has low weight:** `src_cv_interarrival20` had a predictive power of just
  0.56 (near random) in 2.2. Adding jitter barely degrades a model that does not
  rely on it.

In other words, the two decisions we made back then (don't memorize identity;
diversify features) **are the structural defense** against this exact attack. A
naive model would fall to 41%; ours falls far less.

## Immediate mitigation (hours)
1. **Detect the shift:** recall monitor + feature-distribution shift + anomaly
   spike raise the alert (same pipeline as 3.2).
2. **Turn the disguise into a signal:** randomizing the JA3 *is*, in itself,
   anomalous. A source that exhibits **many distinct JA3s within a window** is not
   normal → adding **`ja3_churn` per source** (count of distinct fingerprints)
   makes the evasion **self-incriminating**. The same goes for artificial jitter
   (variance that is too high).
3. **Campaign mode (D18):** temporarily drop the cost threshold → recovers recall
   by accepting more FPs for the duration of the attack.
4. **Unsupervised safety net:** the anomaly layer (which does not use JA3) keeps
   catching the behavioral deviation.
5. **Outside-the-ML:** rate-limiting and **challenge** (JS/PoW) for suspicious
   sources; IP/ASN reputation via threat-intel still applies.

## Architecture changes (long term)
1. **Principle: anchor on the attack's GOAL, not on the disguise.** The attacker
   can randomize JA3 and timing, but **cannot stop doing what they came to do** —
   hitting `/auth/login`, generating credential errors, scanning endpoints.
   Features tied to the *goal* (error rate, focus on sensitive endpoints,
   credential stuffing semantics) are **expensive to fake** without aborting the
   attack.
2. **Defense in depth / feature diversity:** no single feature may dominate. We
   already follow this; reinforce it with regularization and, if needed,
   per-feature importance caps.
3. **Adversarial training:** inject training examples with randomized JA3 and
   jittered timing, so the model **learns not to depend** on those signals.
4. **Variability meta-features:** JA3 churn, timing entropy, UA diversity per
   source — the very *attempt to hide* becomes a feature.
5. **Continuous red-teaming:** the team that simulates attacks (mentioned in the
   brief) feeds the most recent evasions back into the training set → the loop
   closes with 3.2.

## Verdict
The described attack exploits a **dependence on forgeable features** — and we have
already avoided it by design (JA3 out, timing low-weight), so we start from a
defensible position. The complete response is: **turn the evasion into a signal**
(JA3/timing churn becomes a feature), **fall back on the unsupervised layer** and
on **campaign mode** in the short term, and in the long term **anchor the model on
the attack's goal** (what is expensive to fake) with **adversarial training** and
**continuous red-teaming**. Robustness here is a consequence of the feature
decisions, not a later patch.
