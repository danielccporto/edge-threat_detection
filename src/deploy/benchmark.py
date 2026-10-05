"""
2.4 — Benchmark de viabilidade no edge.

Mede, para os modelos treinados: latência por requisição (single-sample),
throughput em lote, tamanho em disco e complexidade (nº de árvores/nós p/ as
árvores; nº de coeficientes p/ o linear).

IMPORTANTE: latência medida em Python/sklearn é um TETO (overhead de intérprete).
No edge real o modelo é compilado para código sem dependências (ver export), bem
mais rápido. O gargalo real do orçamento de 5ms é o cálculo de features + estado
(ver 3.1), não a aritmética do modelo.

Uso: python -m src.deploy.benchmark
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest

from ..modeling.split import TARGET, feature_columns, load_features, temporal_split

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "models"
REPORTS = ROOT / "reports"


def _latency_single(pipe, X, n=500):
    x1 = X.iloc[[0]]
    pipe.predict_proba(x1)  # warmup
    ts = []
    for i in range(n):
        xi = X.iloc[[i % len(X)]]
        t0 = time.perf_counter()
        pipe.predict_proba(xi)
        ts.append((time.perf_counter() - t0) * 1e3)  # ms
    a = np.array(ts)
    return {"mean_ms": round(a.mean(), 4), "p50_ms": round(np.percentile(a, 50), 4),
            "p99_ms": round(np.percentile(a, 99), 4)}


def _throughput(pipe, X):
    t0 = time.perf_counter()
    pipe.predict_proba(X)
    dt = time.perf_counter() - t0
    return {"batch_n": len(X), "total_s": round(dt, 4),
            "req_per_s": int(len(X) / dt)}


def _lgbm_complexity(pipe):
    booster = pipe.named_steps["clf"].booster_
    dump = booster.dump_model()
    n_trees = len(dump["tree_info"])
    nodes = 0
    def count(t):
        nonlocal nodes
        nodes += 1
        if "left_child" in t:
            count(t["left_child"]); count(t["right_child"])
    for ti in dump["tree_info"]:
        count(ti["tree_structure"])
    return {"n_trees": n_trees, "n_nodes": nodes}


def _size_kb(path: Path):
    return round(path.stat().st_size / 1024, 1) if path.exists() else None


def main():
    df = load_features()
    cols = feature_columns(df, include_country=False)
    _, te = temporal_split(df)
    Xte = te[cols]

    out = {}
    for tag in ["lgbm_nocountry", "logreg_nocountry"]:
        p = MODELS / f"{tag}.joblib"
        if not p.exists():
            continue
        pipe = joblib.load(p)
        rec = {"size_kb_joblib": _size_kb(p),
               "latency_single": _latency_single(pipe, Xte),
               "throughput": _throughput(pipe, Xte)}
        if "lgbm" in tag:
            rec["complexity"] = _lgbm_complexity(pipe)
        else:
            clf = pipe.named_steps["clf"]
            rec["complexity"] = {"n_coef": int(clf.coef_.size + 1)}
        out[tag] = rec

    # IsolationForest (camada de anomalia) — treina rápido em benigno p/ medir
    tr, _ = temporal_split(df)
    iso = IsolationForest(n_estimators=200, random_state=42, n_jobs=1)
    iso.fit(tr[~tr[TARGET]][cols])
    x1 = Xte.iloc[[0]]
    iso.score_samples(x1)
    ts = []
    for i in range(500):
        xi = Xte.iloc[[i % len(Xte)]]
        t0 = time.perf_counter()
        iso.score_samples(xi)
        ts.append((time.perf_counter() - t0) * 1e3)
    out["isolationforest"] = {
        "n_estimators": 200,
        "latency_single": {"mean_ms": round(float(np.mean(ts)), 4),
                           "p99_ms": round(float(np.percentile(ts, 99)), 4)},
    }

    print(json.dumps(out, indent=2))
    (REPORTS / "2_4_benchmark.json").write_text(json.dumps(out, indent=2))
    print("\n[WRITE] reports/2_4_benchmark.json")
    return out


if __name__ == "__main__":
    main()
