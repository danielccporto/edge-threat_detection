"""
2.1 — Join temporal dos rótulos de incidente nas requisições individuais.

Regra de rótulo (unidade = request, label propagado da fonte+janela):
    request é MALICIOSA se casar com >=1 incidente ATIVO no seu timestamp:
        (identifier_type='ip'              E source_ip == source_identifier)
     OU (identifier_type='ip_range'        E source_ip ∈ CIDR(source_identifier))
     OU (identifier_type='tls_fingerprint' E tls_fingerprint == source_identifier)
    E SEMPRE: active_from_ts <= event_ts <= active_until_ts

Quando uma request casa com múltiplos incidentes, resolvemos a classe pela
maior `confidence` (desempate por severidade). Benigno = não-rotulado (PU).

Saída: data/interim/labeled_requests.parquet
Uso:   python -m src.labeling.join_labels
"""
from __future__ import annotations

import ipaddress
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
INTERIM = ROOT / "data" / "interim"

CONF_RANK = {"low": 1, "medium": 2, "high": 3}
# severidade para desempate quando confidence empata
SEVERITY = {
    "zero_day_exploit": 5, "ddos_l7": 4, "credential_stuffing": 3,
    "api_abuse": 2, "scanner": 1,
}


def _load() -> tuple[pd.DataFrame, pd.DataFrame]:
    req = pd.read_parquet(INTERIM / "http_requests.parquet")
    inc = pd.read_parquet(INTERIM / "incident_labels.parquet")
    return req, inc


def _build_indexes(inc: pd.DataFrame):
    """Indexa incidentes por tipo para evitar varredura O(n*m)."""
    ip_exact: dict[str, list] = {}
    ja3: dict[str, list] = {}
    ranges: list = []
    for r in inc.itertuples(index=False):
        rec = (r.active_from_ts, r.active_until_ts, r.attack_class,
               str(r.confidence), r.incident_id)
        t, sid = r.identifier_type, r.source_identifier
        if t == "ip":
            ip_exact.setdefault(sid, []).append(rec)
        elif t == "tls_fingerprint":
            ja3.setdefault(sid, []).append(rec)
        elif t == "ip_range":
            ranges.append((ipaddress.ip_network(sid, strict=False), rec))
    return ip_exact, ja3, ranges


def _resolve(matches: list) -> dict:
    """matches: list of (attack_class, confidence, incident_id, match_type)."""
    # ordena por (confidence desc, severidade desc)
    best = max(matches, key=lambda m: (CONF_RANK[m[1]], SEVERITY.get(m[0], 0)))
    return {
        "is_malicious": True,
        "attack_class": best[0],
        "label_confidence": best[1],
        "matched_incident_ids": ",".join(sorted(set(m[2] for m in matches))),
        "match_types": ",".join(sorted(set(m[3] for m in matches))),
        "n_incident_matches": len(set(m[2] for m in matches)),
    }


def join_labels(req: pd.DataFrame, inc: pd.DataFrame) -> pd.DataFrame:
    ip_exact, ja3, ranges = _build_indexes(inc)
    records = []
    for r in req.itertuples(index=False):
        ts = r.event_ts
        matches = []
        for af, au, ac, cf, iid in ip_exact.get(r.source_ip, []):
            if af <= ts <= au:
                matches.append((ac, cf, iid, "ip"))
        for af, au, ac, cf, iid in ja3.get(r.tls_fingerprint, []):
            if af <= ts <= au:
                matches.append((ac, cf, iid, "ja3"))
        if ranges:
            ipa = ipaddress.ip_address(r.source_ip)
            for net, (af, au, ac, cf, iid) in ranges:
                if ipa in net and af <= ts <= au:
                    matches.append((ac, cf, iid, "ip_range"))
        if matches:
            records.append(_resolve(matches))
        else:
            records.append({
                "is_malicious": False, "attack_class": None,
                "label_confidence": None, "matched_incident_ids": "",
                "match_types": "", "n_incident_matches": 0,
            })
    labels = pd.DataFrame.from_records(records, index=req.index)
    out = pd.concat([req, labels], axis=1)
    out["attack_class"] = out["attack_class"].astype("category")
    return out


def main() -> None:
    req, inc = _load()
    out = join_labels(req, inc)
    dest = INTERIM / "labeled_requests.parquet"
    out.to_parquet(dest, index=False)
    print(f"[WRITE] {dest.relative_to(ROOT)}  ({len(out)} linhas)")


if __name__ == "__main__":
    main()
