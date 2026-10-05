"""
2.3 — Split temporal (sem leakage) e seleção de features.

Headline split: treino = 06-10/jan, teste = 11-12/jan (corte no dia 11, D13).
Walk-forward: TimeSeriesSplit sobre os dados ordenados por tempo.

Features EXCLUÍDAS como preditoras (D12): identidade crua (source_ip,
tls_fingerprint) e, nas versões "sem country", também country. request_id/
event_ts são metadados; is_malicious é o alvo.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
INTERIM = ROOT / "data" / "interim"

CUTOFF = pd.Timestamp("2025-01-11T00:00:00+00:00")  # D13
TARGET = "is_malicious"
META = ["request_id", "event_ts", "source_ip", "tls_fingerprint",
        "attack_class", "label_confidence"]
IDENTITY = ["source_ip", "tls_fingerprint"]  # nunca entram como feature


def load_features() -> pd.DataFrame:
    df = pd.read_parquet(INTERIM / "features.parquet")
    return df.sort_values("event_ts").reset_index(drop=True)


def feature_columns(df: pd.DataFrame, include_country: bool) -> list[str]:
    drop = set(META) | {TARGET} | set(IDENTITY)
    if not include_country:
        drop.add("country")
    return [c for c in df.columns if c not in drop]


def temporal_split(df: pd.DataFrame):
    """Retorna (train_df, test_df) pelo corte no dia 11."""
    train = df[df["event_ts"] < CUTOFF]
    test = df[df["event_ts"] >= CUTOFF]
    return train, test


def summary(df: pd.DataFrame) -> str:
    tr, te = temporal_split(df)
    return (f"treino={len(tr)} ({int(tr[TARGET].sum())} mal) | "
            f"teste={len(te)} ({int(te[TARGET].sum())} mal) "
            f"[{100*len(te)/len(df):.0f}% teste]")
