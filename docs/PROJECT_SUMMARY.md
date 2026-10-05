# Understanding the Project from Scratch — CloudWalk Edge Security

> A guided walkthrough of everything we did, for someone just arriving.

## What we're trying to solve

CloudWalk processes billions of HTTP requests per day at the edge of its
infrastructure (the CDN/WAF layer, which sits between the internet and the
company's servers). Part of that traffic is attacks — people trying to guess
passwords, abuse APIs, take down services. Today this is blocked by fixed,
hand-written rules that get a lot wrong: they block legitimate customers during a
sales peak and let clever attackers through.

The mission: build a **machine learning model that decides, in real time, whether
each request is malicious or not** — fast enough to run on the edge itself (under
5 milliseconds per request, no GPU, in a very constrained environment). And with
one costly twist: **blocking a legitimate customer during a payment costs money**,
so erring on the side of blocking is dangerous.

The problem has four underlying difficulties that guided every decision:
1. **Attacks are extremely rare** (less than 0.1% of traffic) — the "needle in the
   haystack".
2. **Labels arrive late and incomplete** — the security team only confirms
   something was an attack days later, and not every attack is discovered.
3. **Attackers change tactics every week** — what worked yesterday fails today.
4. **A single request looks innocent** — the attack only shows up when you look at
   the *sequence* of requests from the same source.

## The data we received

Three tables (spreadsheets), 7 days of simulated traffic:
- **`http_requests`** — the record of each request (50k rows): who sent it (IP),
  when, to which address, what response it got, etc. This is the central table.
- **`request_headers`** — the "headers" of each request (146k rows): technical
  details such as whether the request carried a session cookie, an authentication
  token, etc.
- **`incident_labels`** — the list of incidents confirmed by security (103 rows):
  "IP X was attacking between such-and-such time". This is our ground truth.

## Step 1 — Tidy up the house (standardization)

Raw data comes in dirty: everything arrives as text, column names are
inconsistent, dates are in different formats. Before any analysis, we created a
stage that **converts each field to the right type** (a date becomes a date, a
number becomes a number) and **checks integrity** (no duplicate IDs? no missing
essential fields?). We store the clean result in an efficient format (Parquet)
that **preserves those types**. It's the foundation: without it, silent bugs would
show up down the line.

## Step 2 — Build the ground truth (labeling)

This is where the first subtlety lives. The incident list doesn't say "request 123
was malicious"; it says "IP X was malicious between 3am and 6am". So we had to
**cross-reference** the two: a request is malicious **if** it came from a flagged
source **and** happened within that incident's time window. Respecting the window
is crucial — the same source can be an attacker at dawn and quiet in the afternoon.

Result: **592 malicious requests (1.18%)** against 49,408 benign ones — that is,
**83 benign for every malicious one**. This huge imbalance is the real scenario and
shaped every subsequent choice. We also discovered, while investigating, that many
incidents were "repeats" (the same source flagged several times) and that "benign"
here actually means "was not flagged" — not necessarily "proven clean".

## Step 3 — Turn records into signals (feature engineering)

A model doesn't understand "request"; it understands numbers. So we turned each
request into **35 measurable signals**, in two families:
- **Signals from the request itself:** is the accessed address sensitive (a login
  screen)? was the response an error? is the body tiny? does the program that sent
  it look like a real browser or an automated script?
- **Signals from the source's behavior over time:** how many requests did that IP
  make in the last 5 minutes? what fraction were errors? does it keep hammering a
  single address (typical of an attack) or browse across several (typical of a
  human)?

These behavioral signals are computed **looking only at the past** of each source
(never the future), because that's how the edge works in real life. When we
measured which signals best separate attack from normal traffic, the winners were
precisely the **behavioral** ones — confirming the intuition: the attack reveals
itself in the sequence, not in the isolated request.

## Step 4 — Choose and train the models

We tested two types, deliberately at opposite ends:
- **LightGBM** (a "turbocharged" forest of decision trees) — precise yet still
  small/fast, our main model.
- **Logistic Regression** (a simple linear model) — the lightest possible, to show
  the floor that would fit comfortably on the edge.

Three important methodological precautions:
- **Imbalance:** instead of inventing fake attack data, we told the model to "give
  more weight" to the rare malicious examples.
- **Separation by time (not random):** we trained on the first 5 days and tested
  on the last 2. Since in reality we always predict the future from the past,
  shuffling the days would be cheating (the model would "see the future").
- **We did not give the model the raw "identity"** (the IP or the TLS
  fingerprint). We showed with data that those fields were practically the answer
  copied from the ground truth — the model would memorize the known attackers and
  be useless against any new attacker (which is exactly what happens in practice).

## Step 5 — Distrust the results (the most important part)

The model gave nearly perfect metrics. **That made us suspicious, not happy** — a
perfect result almost always hides a problem. So we ran four tests to interrogate
our own work:
1. **We shuffled the labels** on purpose: the model started getting everything
   wrong (good — it means there is **no bug/leakage** in the code).
2. **We compared against a silly one-line rule:** it nearly tied the model. In
   other words, **the simulated attacks are too easy** to separate; the high score
   reflects the data, not the model's brilliance.
3. **We tested on never-before-seen sources:** the model did reasonably well,
   proving it learned *behavior* rather than memorizing identities.
4. **We hid an entire attack type from training:** the model **could not detect
   it**. This was the decisive finding: a model that only recognizes what it has
   already seen **fails in exactly the scenario that motivates the project** (new
   attacks every week).

## Step 6 — Fix the gap (hybrid model)

How do you solve "doesn't detect novel attacks"? By adding a second model with the
opposite logic: the **IsolationForest**. While the first one learns to recognize
known attacks, this one learns only **what normal traffic looks like** and raises
an alert for anything out of pattern — even an attack it has never seen.

The final decision became: **block if the main model recognizes a known attack OR
if the anomaly detector thinks something is very strange.**

We tested again by hiding each attack type: the hybrid **recovered detection on 4
of the 5 types** (from recall ~0 to 0.67–0.98). The exception, which we report
honestly, is an attack that **mimics legitimate traffic** (slow, no errors) — the
hardest of all, and a point for future work.

## Step 7 — Prove it runs on the edge (deployment feasibility)

The edge is a tight environment (under 5ms per request, no GPU). We measured, and
the result was reassuring: **the model is the cheap part**. The actual decision
math takes **~2 microseconds** per request (2,500× below the limit) and the model
occupies only a few hundred KB. We confirmed this by exporting the final model to
**pure JavaScript, with no dependencies** (a file ready to run in a Cloudflare
Worker). The lesson: the real timing challenge is not the model, but **remembering
each source's recent history** (the "state") in an environment that, by nature,
keeps no memory — the subject of the next part.

> Note: the Logistic Regression mentioned earlier was only a **comparison point**.
> The model going to production is the **hybrid (LightGBM + IsolationForest)**.

## Step 8 — Answer the hard production questions (Part 3)

With the system ready, we faced the four practical dilemmas from the brief:

- **How do you keep "memory" in an environment with no memory? (3.1)** Instead of
  storing each source's entire history, we store a **small summary** (rate, errors,
  variety of accesses) in a piece of state that "belongs" to that source, with a
  local copy for fast reads and the write done *after* responding. What costs time
  is consulting that memory (~milliseconds), not the model. And if that memory goes
  down, the system **degrades safely**: it falls back to using only the signals
  from the isolated request and, on payment screens, prefers **not to block**
  (because blocking a customer is expensive).

- **When should you block, in money terms? (3.3)** We showed that the threshold
  **is not a fixed number, it's a cost calculation**: since blocking a customer
  ($2.50) is 25× more expensive than letting an attack through ($0.10), you should
  only block with **~96% confidence**. But during an intense attack (cost rises to
  $5.00), the math flips and it becomes worth blocking already at **~33%
  confidence**. In other words: the gatekeeper's strictness **changes on its own
  according to the risk of the moment**.

- **And while the attack is new and has no "record" yet? (3.2)** The anomaly
  detector is the **first to respond** (it covers the unknown); when the attack's
  record finally arrives (1–3 days later), the main model **takes over** that
  pattern. We accelerate this cycle by prioritizing investigation of the most
  suspicious cases and retraining frequently.

- **And if the attacker tries to fool the model? (3.4)** The classic attack is to
  change the "fingerprint" and the rhythm of the requests. Here we were lucky to
  have been careful beforehand: **our model already doesn't depend on those fields**
  (we excluded them on purpose), so the trick works poorly against it. On top of
  that, the very attempt to disguise **becomes a clue** (changing fingerprint on
  every request is, in itself, abnormal), and in the long run we anchor the model
  in what the attacker **cannot avoid doing** to achieve their objective.

## Where we are and what's left

We have a **two-layer detection system** (known + anomalous), rigorously evaluated,
with the limits mapped out, **provably deployable on the edge**, and with the **four
production questions answered** (Part 3). All that's left is **packaging**:
- the **end-to-end design writeup** (Part 1), which stitches data → features →
  model → deploy → monitoring into a single narrative;
- the **README** with the step-by-step on how to run the project.

## Summary of the numbers

| What we measured | Result | How to read it |
|---|---|---|
| "Showcase" score on the test | nearly perfect | misleading (easy data) |
| Honest score (temporal validation) | ~0.85–0.92 | the realistic number |
| Detection of a **known** attack | high | strong |
| Detection of a **novel** attack (main only) | ~0 | supervised limit |
| Detection of a **novel** attack (hybrid) | 0.67–0.98 | gap resolved |
| Decision cost per request | ~2µs | 2,500× below the 5ms limit |
| Exported model size | ~259 KB (pure JS) | fits comfortably on the edge |
| Optimal threshold (baseline) | ~96% confidence | blocking is 25× costlier than letting through |
| Threshold (intense attack) | ~33% confidence | strictness adjusts to the risk of the moment |
