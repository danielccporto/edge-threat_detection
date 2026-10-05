"""
2.3 — Pré-processamento por modelo (ColumnTransformer dentro de Pipeline).

Boa prática: o pré-processamento é ajustado SÓ no treino (dentro da Pipeline),
nunca vê o teste → sem leakage; e é serializado junto com o modelo.

- Árvore (LightGBM): numéricas passthrough (invariante a escala, engole cauda
  longa), country → one-hot.
- Linear (LogReg): numéricas de cauda longa → log1p + StandardScaler; demais
  numéricas → StandardScaler; country → one-hot.
"""
from __future__ import annotations

import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler

# numéricas de cauda longa (log1p antes de escalonar no modelo linear)
SKEWED = ["body_size_bytes", "ua_len", "response_time_ms", "path_len",
          "src_cnt20", "src_cnt_5min"]


def _split_cols(feature_cols: list[str]):
    cat = [c for c in feature_cols if c == "country"]
    num = [c for c in feature_cols if c != "country"]
    return num, cat


def tree_preprocessor(feature_cols: list[str]) -> ColumnTransformer:
    num, cat = _split_cols(feature_cols)
    transformers = [("num", "passthrough", num)]
    if cat:
        transformers.append(
            ("cat", OneHotEncoder(handle_unknown="ignore"), cat))
    return ColumnTransformer(transformers, remainder="drop")


def linear_preprocessor(feature_cols: list[str]) -> ColumnTransformer:
    num, cat = _split_cols(feature_cols)
    skewed = [c for c in num if c in SKEWED]
    plain = [c for c in num if c not in SKEWED]
    log1p = FunctionTransformer(np.log1p, feature_names_out="one-to-one")
    transformers = [
        ("skewed", Pipeline([("log", log1p), ("scale", StandardScaler())]), skewed),
        ("plain", StandardScaler(), plain),
    ]
    if cat:
        transformers.append(
            ("cat", OneHotEncoder(handle_unknown="ignore"), cat))
    return ColumnTransformer(transformers, remainder="drop")
