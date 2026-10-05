"""
2.2 — Pipeline de feature engineering.

Duas famílias de features:
  • Per-request: baratas, calculáveis no edge sem estado
      (path, status, método, body, user-agent, headers via flags/contagens).
  • De fonte (rolling CAUSAL por source_ip): agregam SÓ requests anteriores da
      mesma fonte em duas janelas — temporal (5 min) e por contagem (20 req).
      Sem vazamento de futuro; replicável no edge em tempo real (ver 3.1).

Entrada: data/interim/labeled_requests.parquet + request_headers.parquet
Saída:   data/interim/features.parquet
Uso:     python -m src.features.build_features
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
INTERIM = ROOT / "data" / "interim"

TIME_WINDOW = "300s"   # 5 min
COUNT_WINDOW = 20      # últimas 20 requests
SENSITIVE = ("/auth/login", "/auth/refresh", "/cards/tokenize", "/cards")
NON_BROWSER = ("python-requests", "axios", "curl", "go-http", "okhttp",
               "java", "wget", "scrapy", "bot")


# ---------------------------------------------------------------------------
# Per-request
# ---------------------------------------------------------------------------
def per_request_features(df: pd.DataFrame) -> pd.DataFrame:
    f = pd.DataFrame(index=df.index)
    path = df["path"].astype(str)
    base = path.str.split("?", n=1).str[0]

    # path
    query = path.str.extract(r"\?(.*)$", expand=False).fillna("")
    f["path_len"] = path.str.len()
    f["path_depth"] = base.str.count("/")
    f["n_query_params"] = query.str.count("=").astype(int)
    f["path_entropy"] = base.map(_shannon_entropy)
    f["is_sensitive_ep"] = base.apply(
        lambda p: int(any(s in p for s in SENSITIVE)))

    # http
    sc = df["status_code"].astype(int)
    f["status_code"] = sc
    f["status_class"] = (sc // 100).astype(int)
    f["is_error"] = (sc >= 400).astype(int)
    f["is_429"] = (sc == 429).astype(int)
    f["response_time_ms"] = df["response_time_ms"].astype(int)
    f["body_size_bytes"] = df["body_size_bytes"].astype(int)

    # método (one-hot leve — só 6 valores)
    for m in ["GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS"]:
        f[f"method_{m}"] = (df["method"].astype(str) == m).astype(int)

    # user-agent
    ua = df["user_agent"].astype(str).str.lower()
    f["ua_non_browser"] = ua.apply(
        lambda s: int(any(k in s for k in NON_BROWSER)))
    f["ua_len"] = ua.str.len()

    # tempo do dia (hora) — sazonalidade de tráfego
    f["hour"] = df["event_ts"].dt.hour
    return f


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = pd.Series(list(s)).value_counts(normalize=True)
    return float(-(counts * np.log2(counts)).sum())


# ---------------------------------------------------------------------------
# Headers (flags + contagens) — D9
# ---------------------------------------------------------------------------
def header_features(req_index: pd.Index, req_ids: pd.Series,
                    headers: pd.DataFrame) -> pd.DataFrame:
    h = headers.copy()
    h["header_name"] = h["header_name"].astype(str)
    present = h.groupby("request_id")["header_name"].agg(set)
    n_headers = h.groupby("request_id")["header_name"].size()

    def has(rid, name):
        s = present.get(rid)
        return int(s is not None and name in s)

    out = pd.DataFrame(index=req_index)
    out["n_headers"] = req_ids.map(n_headers).fillna(0).astype(int)
    for col, name in [("has_cookie", "Cookie"),
                      ("has_authorization", "Authorization"),
                      ("has_referer", "Referer"),
                      ("has_content_type", "Content-Type"),
                      ("has_accept_language", "Accept-Language")]:
        out[col] = req_ids.map(lambda r: has(r, name)).astype(int)
    return out


# ---------------------------------------------------------------------------
# Rolling causal por fonte (source_ip) — D8
# ---------------------------------------------------------------------------
def source_rolling_features(df: pd.DataFrame) -> pd.DataFrame:
    base = df[["source_ip", "event_ts", "path", "status_code", "method"]].copy()
    base = base.sort_values("event_ts")
    base["is_error"] = (base["status_code"].astype(int) >= 400).astype(int)
    base["is_post"] = (base["method"].astype(str) == "POST").astype(int)
    base["path_code"] = base["path"].astype("category").cat.codes
    base["status_int"] = base["status_code"].astype(int)
    base["dummy"] = 1

    parts = []
    for _, g in base.groupby("source_ip", sort=False):
        g = g.sort_values("event_ts")
        r = g.rolling(COUNT_WINDOW, min_periods=1)
        g["src_cnt20"] = r["dummy"].count()
        g["src_err_rate20"] = r["is_error"].mean()
        g["src_endpoint_div20"] = g["path_code"].rolling(
            COUNT_WINDOW, min_periods=1).apply(lambda x: len(np.unique(x)), raw=True)
        g["src_status_div20"] = g["status_int"].rolling(
            COUNT_WINDOW, min_periods=1).apply(lambda x: len(np.unique(x)), raw=True)
        # regularidade de timing: coef. de variação dos intervalos (bot = baixo)
        dt = g["event_ts"].diff().dt.total_seconds()
        g["src_cv_interarrival20"] = dt.rolling(COUNT_WINDOW, min_periods=2).apply(
            lambda x: (np.nanstd(x) / np.nanmean(x)) if np.nanmean(x) > 0 else 0.0,
            raw=True).fillna(0.0)

        gt = g.set_index("event_ts")
        g["src_cnt_5min"] = gt["dummy"].rolling(TIME_WINDOW).count().to_numpy()
        g["src_err_rate_5min"] = gt["is_error"].rolling(TIME_WINDOW).mean().to_numpy()
        g["src_post_ratio_5min"] = gt["is_post"].rolling(TIME_WINDOW).mean().to_numpy()
        g["src_rate_5min"] = g["src_cnt_5min"] / 300.0
        parts.append(g)

    feats = pd.concat(parts).sort_index()
    cols = [c for c in feats.columns if c.startswith("src_")]
    return feats[cols].reindex(df.index)


# ---------------------------------------------------------------------------
# Orquestração
# ---------------------------------------------------------------------------
def build() -> pd.DataFrame:
    df = pd.read_parquet(INTERIM / "labeled_requests.parquet")
    headers = pd.read_parquet(INTERIM / "request_headers.parquet")

    per_req = per_request_features(df)
    hdr = header_features(df.index, df["request_id"], headers)
    src = source_rolling_features(df)

    keep = ["request_id", "event_ts", "source_ip", "tls_fingerprint",
            "country", "is_malicious", "attack_class", "label_confidence"]
    out = pd.concat([df[keep], per_req, hdr, src], axis=1)
    return out


def main() -> None:
    out = build()
    dest = INTERIM / "features.parquet"
    out.to_parquet(dest, index=False)
    feat_cols = [c for c in out.columns if c not in (
        "request_id", "event_ts", "source_ip", "tls_fingerprint", "country",
        "is_malicious", "attack_class", "label_confidence")]
    print(f"[WRITE] {dest.relative_to(ROOT)}  ({len(out)} linhas, "
          f"{len(feat_cols)} features)")
    print("Features:", feat_cols)
    print("\nChecagem rápida — médias por classe:")
    show = ["src_rate_5min", "src_cv_interarrival20", "src_err_rate20",
            "ua_non_browser", "is_sensitive_ep", "src_endpoint_div20"]
    print(out.groupby("is_malicious")[show].mean().round(3).to_string())


if __name__ == "__main__":
    main()
