"""
Camada de ingestão/padronização.

Lê os CSVs brutos de `data/raw/`, aplica padronização leve de nomes, casting
tipado (datetime UTC, int, categóricos), normalização mínima das chaves de
join (trim de IP, validação de CIDR/JA3) e valida contratos de schema.
Persiste o resultado tipado em `data/interim/*.parquet`.

Uso:
    python -m src.ingestion.standardize            # processa e grava parquet
    python -m src.ingestion.standardize --check    # só valida, não grava
"""
from __future__ import annotations

import argparse
import ipaddress
from pathlib import Path

import pandas as pd

from . import schema as S

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
INTERIM = ROOT / "data" / "interim"


# ---------------------------------------------------------------------------
# Helpers de normalização
# ---------------------------------------------------------------------------
def _to_utc(series: pd.Series) -> pd.Series:
    """Parse datetime garantindo tz-aware em UTC."""
    return pd.to_datetime(series, utc=True, errors="raise")


def _valid_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value.strip())
        return True
    except ValueError:
        return False


def _valid_cidr(value: str) -> bool:
    try:
        ipaddress.ip_network(value.strip(), strict=False)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Loaders (uma função por tabela)
# ---------------------------------------------------------------------------
def load_requests() -> pd.DataFrame:
    df = pd.read_csv(RAW / "http_requests.csv", dtype=str)
    df = df.rename(columns=S.REQUESTS_RENAME)

    df["event_ts"] = _to_utc(df["event_ts"])
    for col in S.INT_COLS["http_requests"]:
        df[col] = pd.to_numeric(df[col], errors="raise").astype("int64")

    # normalização das chaves de join
    df["source_ip"] = df["source_ip"].str.strip()
    df["tls_fingerprint"] = df["tls_fingerprint"].str.strip()

    # derivada: asn numérico (preserva o original)
    df["asn_num"] = (
        df["asn"].str.extract(r"AS(\d+)", expand=False).astype("Int64")
    )

    for col in S.CATEGORICAL_COLS["http_requests"]:
        df[col] = df[col].astype("category")

    _validate(df, "http_requests")
    return df.sort_values("event_ts").reset_index(drop=True)


def load_headers() -> pd.DataFrame:
    df = pd.read_csv(RAW / "request_headers.csv", dtype=str)
    df = df.rename(columns=S.HEADERS_RENAME)
    df["header_name"] = df["header_name"].str.strip()
    for col in S.CATEGORICAL_COLS["request_headers"]:
        df[col] = df[col].astype("category")
    _validate(df, "request_headers")
    return df.reset_index(drop=True)


def load_incidents() -> pd.DataFrame:
    df = pd.read_csv(RAW / "incident_labels.csv", dtype=str)
    df = df.rename(columns=S.INCIDENTS_RENAME)

    for col in S.DATETIME_UTC_COLS["incident_labels"]:
        df[col] = _to_utc(df[col])
    for col in S.DATE_COLS["incident_labels"]:
        df[col] = _to_utc(df[col]).dt.date

    df["source_identifier"] = df["source_identifier"].str.strip()

    # confidence como categórico ORDENADO -> permite comparação e vira peso
    df["confidence"] = pd.Categorical(
        df["confidence"], categories=S.CONFIDENCE_ORDER, ordered=True
    )
    for col in S.CATEGORICAL_COLS["incident_labels"]:
        df[col] = df[col].astype("category")

    # validação dos identificadores conforme o tipo
    bad = []
    for _, r in df.iterrows():
        t, sid = r["identifier_type"], r["source_identifier"]
        if t == "ip" and not _valid_ip(sid):
            bad.append(("ip", sid))
        elif t == "ip_range" and not _valid_cidr(sid):
            bad.append(("ip_range", sid))
        elif t == "tls_fingerprint" and not sid.startswith("ja3_"):
            bad.append(("tls_fingerprint", sid))
    if bad:
        raise ValueError(f"source_identifier inválidos: {bad[:10]}")

    # sanidade temporal: active_from <= active_until
    bad_win = df[df["active_from_ts"] > df["active_until_ts"]]
    if len(bad_win):
        raise ValueError(f"{len(bad_win)} incidentes com janela invertida")

    _validate(df, "incident_labels")
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Contrato de schema
# ---------------------------------------------------------------------------
def _validate(df: pd.DataFrame, table: str) -> None:
    # unicidade da PK
    pk = S.PRIMARY_KEYS[table]
    dups = df.duplicated(subset=pk).sum()
    if dups:
        raise ValueError(f"[{table}] {dups} PKs duplicadas em {pk}")

    # colunas não-nulas
    for col in S.NON_NULL_COLS.get(table, []):
        n = df[col].isna().sum()
        if n:
            raise ValueError(f"[{table}] coluna '{col}' tem {n} nulos")

    # domínios esperados
    for key, allowed in S.EXPECTED_DOMAINS.items():
        tbl, col = key.split(".")
        if tbl == table and col in df.columns:
            seen = set(df[col].dropna().astype(str).unique())
            extra = seen - allowed
            if extra:
                raise ValueError(f"[{table}] '{col}' valores inesperados: {extra}")


# ---------------------------------------------------------------------------
# Orquestração
# ---------------------------------------------------------------------------
def run(write: bool = True) -> dict[str, pd.DataFrame]:
    tables = {
        "http_requests": load_requests(),
        "request_headers": load_headers(),
        "incident_labels": load_incidents(),
    }
    for name, df in tables.items():
        print(f"[OK] {name:<16} {len(df):>7} linhas | colunas: {list(df.columns)}")
    if write:
        INTERIM.mkdir(parents=True, exist_ok=True)
        for name, df in tables.items():
            out = INTERIM / f"{name}.parquet"
            df.to_parquet(out, index=False)
            print(f"[WRITE] {out.relative_to(ROOT)}")
    return tables


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="só valida, não grava")
    args = ap.parse_args()
    run(write=not args.check)
