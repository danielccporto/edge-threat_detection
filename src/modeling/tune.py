"""
2.3 — Busca leve de hiperparâmetros do LightGBM, orientada à restrição de edge.

Princípio: NÃO caçar métrica (a tarefa está saturada), e sim achar o **menor
modelo** (menos árvores/folhas → menor footprint/latência no WASM) cuja
performance honesta não cai. Validação é TimeSeriesSplit SÓ no treino (sem
leakage do teste); métrica = PR-AUC médio nos folds com positivos.

Regra de seleção: entre as configs dentro de `TOL` do melhor PR-AUC médio,
escolhe a de MENOR tamanho (proxy = n_estimators × num_leaves).

Uso: python -m src.modeling.tune
"""
from __future__ import annotations

import itertools
from pathlib import Path

import numpy as np
from lightgbm import LGBMClassifier
from sklearn.metrics import average_precision_score
from sklearn.model_selection import TimeSeriesSplit

from .split import TARGET, feature_columns, load_features, temporal_split

ROOT = Path(__file__).resolve().parents[2]
TOL = 0.01          # tolerância de PR-AUC vs melhor
N_SPLITS = 4

GRID = {
    "n_estimators": [60, 120, 200],
    "max_depth": [3, 4, 6],
    "num_leaves": [7, 15, 31],
    "learning_rate": [0.05, 0.1],
}


def _valid(cfg) -> bool:
    return cfg["num_leaves"] <= 2 ** cfg["max_depth"]


def _cv_prauc(X, y, cfg) -> float:
    tscv = TimeSeriesSplit(n_splits=N_SPLITS)
    scores = []
    for tr, va in tscv.split(X):
        if y.iloc[va].sum() == 0 or y.iloc[tr].sum() == 0:
            continue
        clf = LGBMClassifier(class_weight="balanced", subsample=0.8,
                             colsample_bytree=0.8, random_state=42,
                             verbose=-1, **cfg)
        clf.fit(X.iloc[tr], y.iloc[tr])
        p = clf.predict_proba(X.iloc[va])[:, 1]
        scores.append(average_precision_score(y.iloc[va], p))
    return float(np.mean(scores)) if scores else np.nan


def search():
    df = load_features()
    cols = feature_columns(df, include_country=False)
    train, _ = temporal_split(df)
    X, y = train[cols], train[TARGET].astype(int)

    keys = list(GRID)
    results = []
    for combo in itertools.product(*GRID.values()):
        cfg = dict(zip(keys, combo))
        if not _valid(cfg):
            continue
        prauc = _cv_prauc(X, y, cfg)
        size = cfg["n_estimators"] * cfg["num_leaves"]
        results.append({**cfg, "prauc": round(prauc, 4), "size": size})

    results = [r for r in results if not np.isnan(r["prauc"])]
    best = max(r["prauc"] for r in results)
    within = [r for r in results if r["prauc"] >= best - TOL]
    chosen = min(within, key=lambda r: r["size"])
    return results, best, chosen


def build_report() -> str:
    results, best, chosen = search()
    L = []; w = L.append
    w("# 2.3 — Tuning leve do LightGBM (orientado a edge)\n")
    w(f"- Validação: TimeSeriesSplit({N_SPLITS}) no treino; métrica = PR-AUC médio.")
    w(f"- Melhor PR-AUC na busca: **{best:.4f}**; tolerância: {TOL}.")
    w(f"- Regra: menor modelo (n_estimators×num_leaves) dentro da tolerância.\n")
    w("## Config escolhida")
    w(f"```\n{ {k: chosen[k] for k in GRID} }\n"
      f"PR-AUC={chosen['prauc']}  size(proxy)={chosen['size']}\n```\n")
    w("## Top 8 por PR-AUC (e seus tamanhos)")
    w("| n_est | depth | leaves | lr | PR-AUC | size |")
    w("|---|---|---|---|---|---|")
    for r in sorted(results, key=lambda r: (-r["prauc"], r["size"]))[:8]:
        w(f"| {r['n_estimators']} | {r['max_depth']} | {r['num_leaves']} "
          f"| {r['learning_rate']} | {r['prauc']} | {r['size']} |")
    w("\n## Menores modelos dentro da tolerância")
    within = [r for r in results if r["prauc"] >= best - TOL]
    for r in sorted(within, key=lambda r: r["size"])[:6]:
        w(f"- size={r['size']} (n_est={r['n_estimators']}, depth={r['max_depth']}, "
          f"leaves={r['num_leaves']}, lr={r['learning_rate']}) → PR-AUC={r['prauc']}")
    w("\n> Escolhemos o modelo mais enxuto que não perde performance honesta — "
      "insumo direto para a viabilidade de edge (2.4).")
    return "\n".join(L)


def main() -> None:
    text = build_report()
    print(text)
    (ROOT / "reports" / "2_3_tuning.md").write_text(text, encoding="utf-8")
    print("\n[WRITE] reports/2_3_tuning.md")


if __name__ == "__main__":
    main()
