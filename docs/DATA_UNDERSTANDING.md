# Data Understanding — CloudWalk Edge Security Case

> Reference document for the exploration phase. Basis: 7 days of synthetic
> traffic (2025-01-06 → 2025-01-12) that passed through the edge/WAF layer.

## File overview (`data/raw/`)

| File | Grain (1 row =) | Rows | PK |
|---|---|---|---|
| `http_requests.csv` | 1 HTTP request | 50,000 | `request_id` |
| `request_headers.csv` | 1 header of 1 request | 146,439 | (`request_id`, `header_name`) |
| `incident_labels.csv` | 1 incident label (source + window) | 103 | `incident_id` |

---

## 1. `http_requests` — central fact table

Request-level log. It is the project's **backbone**: everything links to it.

| Column | Type | Role | Notes |
|---|---|---|---|
| `request_id` | hex string | **PK** | 50,000 unique, no nulls |
| `timestamp` | ISO8601 UTC | temporal | window 2025-01-06T00:01 → 2025-01-12T21:31; used in the temporal split and in the join with incident |
| `source_ip` | IPv4 | **logical FK** to incident (ip / ip_range) | 1,353 distinct IPs |
| `method` | enum | feature | GET, POST, PUT, DELETE, HEAD, OPTIONS |
| `path` | string | feature | 3,508 distinct (varied query strings/paths) |
| `status_code` | int | feature | 10 values; concentrated in 200/201, but there are 4xx/5xx and 429 |
| `response_time_ms` | int | feature | origin latency |
| `body_size_bytes` | int | feature | body size |
| `user_agent` | string | feature | **only 14 distinct** (synthetic); includes browsers and clients `python-requests`, `axios` |
| `tls_fingerprint` | ja3 string | **logical FK** to incident (tls_fingerprint) | **only 9 distinct JA3** in the entire dataset |
| `country` | ISO2 | feature | 16 countries; 69% BR, 15% US |
| `asn` | string ASxxxx | feature | 268 ASNs |

No empty values in any column.

## 2. `request_headers` — detail (long format) 1:N with requests

Key-value format (EAV). Each request has on average **2.93 headers**.

- **FK:** `request_headers.request_id → http_requests.request_id`. **Perfect**
  integrity: 0 orphans, 0 requests without a header.
- **Composite PK:** (`request_id`, `header_name`) — 100% unique (no header
  repeats within the same request).
- 9 distinct `header_name`. Frequency: `Accept` (42k), `Accept-Language` (29k),
  `Accept-Encoding` (21k), `Content-Type` (18k), `Cookie` (12k), `Referer`
  (10k), `Authorization` (7k), `X-Request-ID` (4k), `User-Agent` (6).
- Rich signals for features: presence/absence of `Cookie`/`Authorization`
  (authenticated session?), `Accept-Language` consistent with `country`,
  `Content-Type` vs `method`, absence of `Referer`.
- **To use in ML it must be pivoted** (long → wide: one column per header) or
  derived into flags/counts per `request_id`.

## 3. `incident_labels` — labels (delayed, source-level ground truth)

It does NOT label requests directly — it labels **sources within time
windows**. Hence the need for the temporal join.

| Column | Role |
|---|---|
| `incident_id` | PK (103 unique) |
| `source_identifier` | the source identifier (42 distinct — sources recur across multiple incidents) |
| `identifier_type` | **how to match**: `ip` (exact match), `ip_range` (CIDR → contains), `tls_fingerprint` (exact match on the ja3) |
| `attack_class` | credential_stuffing, api_abuse, ddos_l7, scanner, zero_day_exploit |
| `confidence` | high (64) / medium (28) / low (11) → label weight |
| `labeled_at` | when the label was created (**delay**: days after the attack) |
| `active_from` / `active_until` | the label's **validity window**; valid only for requests whose `timestamp` falls within it |

Distribution (`identifier_type` × `attack_class`): most are `ip` (89), with 8
`ip_range` and 6 `tls_fingerprint`. ddos_l7 dominates the incident count.

---

## Join model (how to combine)

```
request_headers.request_id  ──N:1──►  http_requests.request_id   (direct FK, exact)

http_requests  ──many:many (conditional)──►  incident_labels
   match condition (OR across the 3):
     • identifier_type='ip'              AND source_ip == source_identifier
     • identifier_type='ip_range'        AND source_ip ∈ CIDR(source_identifier)
     • identifier_type='tls_fingerprint' AND tls_fingerprint == source_identifier
   AND ALWAYS: active_from <= timestamp <= active_until   (temporal bound)
```

Labeling rule: a request is **malicious** if it matches ≥1 incident active at
its timestamp; otherwise **benign** (positive-unlabeled — see the gaps).

## Join simulation result (preview of task 2.1)

- **592 malicious (1.18%)** vs **49,408 benign (98.82%)**.
- By class (1st match): credential_stuffing 249, ddos_l7 247, api_abuse 65,
  scanner 25, zero_day 6.
- Matches by type: ip 557, ip_range 313, ja3 567 (they sum to >592 because the
  same request matches simultaneously by ip+range+ja3; 0 class conflicts).

## Labeling gaps and ambiguities (discussion required in 2.1)

1. **Window outside the log period:** INC-0071 (api_abuse, Jan 13-14) is after
   the last log (Jan 12) → it labels nothing. This reflects the real delay of
   labels.
2. **Partial coverage (label recall):** incident_labels only covers attacks that
   have already been investigated forensically. Benign = "unlabeled", not
   "provably clean" → a **Positive-Unlabeled** problem; FNs in the labels become
   noise in training.
3. **Identifier overlap:** an IP can fall under `ip` and `ip_range` at the same
   time. We need to deduplicate per request and decide the class (there was no
   conflict here, but the code must be robust to it).
4. **Heterogeneous confidence:** `low`/`medium` labels are noisier — candidates
   for sample weighting or for exclusion in validation.
5. **Source granularity:** ip_range labels the entire range — it can sweep in
   legitimate IPs sharing the CIDR (risk of a false positive in the label).
6. **Sample prevalence (1.18%) ≠ production (<0.1%):** attacks were amplified in
   the synthetic data; threshold calibration should assume the real production
   prevalence, not the dataset's.

---

## On the missing 4th source (`threat_intel_feed`)

Cited in Part 1 and **not delivered** as a CSV. The Part 2 deliverables
explicitly ask only for the 3 files above → **the implementation is 100% viable
without it**. The feed enters as a **design component** (enrichment feature /
fast-path rule) in the write-up of Parts 1 and 3, treated as an external signal
with ~30% coverage. Optionally, we can derive a proxy for the feed from the
high-confidence incidents themselves, making it clear that it's a simulation.
