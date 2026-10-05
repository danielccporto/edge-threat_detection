# 3.1 — Stateless Edge, Stateful Signals

**Problem:** the strongest features (`src_rate_5min`, `src_err_rate20`, …)
require remembering each source's recent history. But the edge is stateless:
each request can land on a different PoP, with no shared memory. How do we keep
session context without blowing the 5ms budget?

## Principle: store *aggregate state*, not events

We don't store the source's list of requests (it grows without bound and makes
reads expensive). We keep a **fixed-size summary per source** (~hundreds of
bytes), updatable in O(1):
- **Time-decayed counters (EWMA)** for rate and error rate — instead of
  recounting a window, we apply exponential decay on each event.
- **Ring buffer of the last 20** (or recent timestamps) for the count features.
- **Cardinality sketch** (a small HyperLogLog) for endpoint diversity.

This keeps the state tiny and the update cheap — essential for fitting the
budget.

## Concrete architecture (Cloudflare pattern)

```
Request
  │
  ├─ routes by SOURCE KEY (hash of IP/JA3) → always the SAME Durable Object
  │
  ▼
Worker (PoP)
  1. read local in-memory cache on the PoP (best-effort)   ~µs
  2. on miss, read the source's Durable Object (co-located) ~1–to a few ms
  3. compute per-request features (inline) + state features
  4. scoreRequest(features) + anomaly                       ~µs
  5. decision (OR + threshold)                              → allow/throttle/block
  6. update the state in WRITE-BEHIND (off the hot path)
```

Three choices that solve "every request on a different node":
- **Routing by key (sticky by source):** the source hash always leads to the
  same **Durable Object** (DO) — one object per source, with serialized,
  consistent updates. This way the "different node" stops being a problem: the
  source state has a single, co-located owner.
- **PoP local cache** as the first layer (reads in µs); the DO is the source of
  truth when there's a miss.
- **Write-behind:** the state update happens **after** responding, so it doesn't
  block the decision.

## Latency implications

- Local read (PoP cache): ~µs. Read of the co-located DO: ~1 to a few ms.
  **This is the largest term in the budget** — the model (~2µs) is negligible
  next to it.
- To fit within the 5ms: (a) **co-locate** state and computation (DO in the same
  region), (b) **sticky routing** by source to maximize cache hits and avoid
  hops between regions, (c) **write-behind** to take the write off the hot path,
  (d) read only what's needed (the aggregate summary, not events).
- Result: the hot path is dominated by **a single state read**; everything else
  is µs.

## What breaks if the state store goes down (graceful degradation)

If the DO/KV becomes unavailable, we lose the `src_*` features — precisely the
most predictive ones. The system **cannot simply fail**; it degrades in layers:

1. **Degraded mode (per-request only):** since we separate per-request features
   from source features, there's a **fallback model** that uses only local
   signals (status/error, non-browser UA, headers, path). It loses recall but
   stays functional without state.
2. **Local anomaly layer + reputation:** the IsolationScore over per-request
   features and the threat-intel (reputation) boolean remain valid without
   shared state.
3. **PoP local counters:** even without the central store, each PoP keeps an
   approximate in-memory view — worse than the global one, better than nothing.
4. **Fail-open vs fail-closed policy:** since **FP is expensive** (blocking a
   payment), during a state outage we lean toward **fail-open on the decision to
   block sensitive flows** (don't block on a degraded signal), while keeping
   **coarse local rate-limiting** as a safety net. This is a business decision,
   stated explicitly.

**Known weak spot:** with state kept only locally per PoP, a source that
rotates across PoPs escapes the local counters — mitigated by sticky routing by
key to the DO (state with a single owner).

## Connection to the rest
This closes the caveat from 2.4: the model is not the latency/throughput
bottleneck; the **state read is**. The design above keeps the hot path at ~1
read + µs of computation, and degrades safely (biased toward not blocking a
legitimate client) when the state fails.
