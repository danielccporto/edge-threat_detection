# 2.2 — Feature Catalog and Rationale

Pipeline: `src/features/build_features.py` → `data/interim/features.parquet`
(50,000 rows × 35 features). Two families (see decisions D8/D9).

## A. Per-request (stateless — computable at the edge in isolation)

| Feature | What it is | Why |
|---|---|---|
| `path_len`, `path_depth`, `n_query_params`, `path_entropy` | URL characteristics | anomalous paths / scanner fuzzing |
| `is_sensitive_ep` | hits /auth/login, /cards/tokenize... | credential stuffing / card testing targets |
| `status_code`, `status_class`, `is_error`, `is_429` | response | attacks generate lots of 401/403/404/429 |
| `response_time_ms`, `body_size_bytes` | size/latency | bots send minimal/uniform bodies |
| `method_*` (6 flags) | HTTP verb | patterns by attack type (e.g., POST on login) |
| `ua_non_browser`, `ua_len` | user-agent | `python-requests`/`axios`/`curl` clients = automation |
| `hour` | hour of day | seasonality of legitimate traffic |

## B. Headers (flags + counts — D9)

`n_headers`, `has_cookie`, `has_authorization`, `has_referer`,
`has_content_type`, `has_accept_language`. Bots tend to send **few headers** and
without a coherent `Referer`/`Accept-Language`.

## C. Source-level — causal rolling by `source_ip` (D8)

Dual window: temporal (5 min) and count (last 20 req). They aggregate only the
same source's past (no leakage; servable at the edge in real time).

| Feature | Signal |
|---|---|
| `src_cnt_5min`, `src_rate_5min` | volume/burst (ddos, brute force) |
| `src_cnt20` | recent activity |
| `src_err_rate20`, `src_err_rate_5min` | error fraction — **enumeration/credential stuffing** |
| `src_endpoint_div20` | endpoint diversity — an attack focuses on few |
| `src_status_div20` | status diversity |
| `src_post_ratio_5min` | POST proportion |
| `src_cv_interarrival20` | timing regularity (coefficient of variation of the intervals) |

## Predictive power — empirical evidence (univariate AUC)

Each feature in isolation vs. `is_malicious` (absolute power = max(AUC, 1−AUC);
AUC<0.5 = inverse relationship). Top features:

| Feature | AUC | Power | Direction |
|---|---|---|---|
| `src_err_rate20` | 0.911 | **0.911** | ↑ error → malicious |
| `src_endpoint_div20` | 0.126 | **0.874** | ↓ diversity → malicious |
| `src_err_rate_5min` | 0.870 | 0.870 | ↑ |
| `status_class` / `is_error` / `status_code` | ~0.85 | ~0.85 | ↑ error |
| `n_headers` | 0.162 | 0.838 | ↓ headers → malicious |
| `body_size_bytes` | 0.211 | 0.789 | ↓ body → malicious |
| `ua_non_browser` | 0.755 | 0.755 | ↑ automation |
| `src_rate_5min` / `src_cnt_5min` | 0.747 | 0.747 | ↑ volume |

**Conclusion (answers 2.2):** the features with the **greatest power** are the
**source-level aggregates** (error rate, endpoint diversity, volume) + automation
signals (non-browser UA, few headers, small body). This confirms the hypothesis:
the attack signal emerges in the **behavior of the sequence**, not in the
isolated request — exactly what motivates the causal rolling window.

**Relevant observation for 3.4 (adversarial robustness):**
`src_cv_interarrival20` had low power (0.56) in this sample — timing is not a
strong discriminator here, and an attacker who adds jitter barely degrades a
model that doesn't depend on it. Diversifying the features (not concentrating on
timing/JA3) is a structural defense.
