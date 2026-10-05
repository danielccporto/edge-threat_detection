"""
2.3 — Treino do baseline: LightGBM (principal) + Regressão Logística (edge),
cada um em duas versões (com / sem `country`) para quantificar o vazamento (D12).

- Imbalance: class_weight='balanced' só no treino (D11).
- Split temporal corte dia 11 + walk-forward (D13).
- Reporta precision/recall/F1/FPR @0.5 e @limiar-F1 (escolhido no treino),
  PR-AUC, ROC-AUC, recall por attack_class no teste, feature importance.

Saídas: models/*.joblib, reports/2_3_model_report.md
Uso:    python -m src.modeling.train
"""
from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline

from . import evaluate as ev
from .preprocess import linear_preprocessor, tree_preprocessor
from .split import (TARGET, feature_columns, load_features, summary,
                    temporal_split)

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "models"
REPORTS = ROOT / "reports"


def make_pipeline(kind: str, feature_cols: list[str]) -> Pipeline:
    if kind == "lgbm":
        pre = tree_preprocessor(feature_cols)
        # params do tuning leve orientado a edge (src/modeling/tune.py):
        # menor modelo dentro da tolerância de PR-AUC (CV temporal no treino).
        clf = LGBMClassifier(
            n_estimators=120, max_depth=6, num_leaves=15, learning_rate=0.1,
            class_weight="balanced", subsample=0.8, colsample_bytree=0.8,
            random_state=42, verbose=-1)
    elif kind == "logreg":
        pre = linear_preprocessor(feature_cols)
        clf = LogisticRegression(
            class_weight="balanced", max_iter=1000, random_state=42)
    else:
        raise ValueError(kind)
    return Pipeline([("pre", pre), ("clf", clf)])


def run_config(df, kind: str, include_country: bool) -> dict:
    cols = feature_columns(df, include_country)
    train, test = temporal_split(df)
    Xtr, ytr = train[cols], train[TARGET].astype(int)
    Xte, yte = test[cols], test[TARGET].astype(int)

    pipe = make_pipeline(kind, cols)
    pipe.fit(Xtr, ytr)

    ptr = pipe.predict_proba(Xtr)[:, 1]
    pte = pipe.predict_proba(Xte)[:, 1]
    thr = ev.best_f1_threshold(ytr, ptr)  # limiar escolhido no TREINO

    res = {
        "kind": kind, "include_country": include_country, "n_features": len(cols),
        "ti": ev.threshold_independent(yte, pte),
        "m_default": ev.metrics_at(yte, pte, 0.5),
        "m_tuned": ev.metrics_at(yte, pte, thr),
    }
    # recall por attack_class no teste (classes presentes)
    tedf = test.copy()
    tedf["pred"] = (pte >= thr).astype(int)
    per_class = {}
    for ac, grp in tedf[tedf[TARGET]].groupby("attack_class", observed=True):
        if len(grp):
            per_class[str(ac)] = round(float(grp["pred"].mean()), 3)
    res["recall_by_class"] = per_class

    # feature importance (só lgbm)
    if kind == "lgbm":
        clf = pipe.named_steps["clf"]
        names = pipe.named_steps["pre"].get_feature_names_out()
        imp = sorted(zip(names, clf.feature_importances_),
                     key=lambda x: -x[1])[:12]
        res["importance"] = [(n.split("__")[-1], int(v)) for n, v in imp]

    MODELS.mkdir(exist_ok=True)
    tag = f"{kind}_{'with' if include_country else 'no'}country"
    joblib.dump(pipe, MODELS / f"{tag}.joblib")
    return res


def walk_forward(df, kind: str, include_country: bool, n_splits=4) -> dict:
    cols = feature_columns(df, include_country)
    X, y = df[cols], df[TARGET].astype(int)
    tscv = TimeSeriesSplit(n_splits=n_splits)
    praucs, f1s = [], []
    for tr_idx, te_idx in tscv.split(X):
        if y.iloc[te_idx].sum() == 0 or y.iloc[tr_idx].sum() == 0:
            continue
        pipe = make_pipeline(kind, cols)
        pipe.fit(X.iloc[tr_idx], y.iloc[tr_idx])
        p = pipe.predict_proba(X.iloc[te_idx])[:, 1]
        ti = ev.threshold_independent(y.iloc[te_idx], p)
        praucs.append(ti["pr_auc"])
        thr = ev.best_f1_threshold(y.iloc[tr_idx],
                                   pipe.predict_proba(X.iloc[tr_idx])[:, 1])
        f1s.append(ev.metrics_at(y.iloc[te_idx], p, thr)["f1"])
    return {"folds": len(praucs),
            "pr_auc_mean": round(float(np.mean(praucs)), 4) if praucs else None,
            "pr_auc_std": round(float(np.std(praucs)), 4) if praucs else None,
            "f1_mean": round(float(np.mean(f1s)), 4) if f1s else None,
            "f1_std": round(float(np.std(f1s)), 4) if f1s else None}


def build_report(df, results, wf) -> str:
    L = []; w = L.append
    w("# 2.3 — Relatório do Modelo Baseline\n")
    w(f"- Split temporal (corte 11/jan): {summary(df)}")
    w("- Imbalance: `class_weight='balanced'` só no treino. Limiar 'tuned' = "
      "F1-ótimo escolhido no TREINO e aplicado ao teste (threshold livre de "
      "leakage; calibração por custo fica na 3.3).\n")

    w("## Métricas no teste (11-12/jan)\n")
    w("| Modelo | country | feats | PR-AUC | ROC-AUC | "
      "P@tuned | R@tuned | F1@tuned | FPR@tuned | P@0.5 | R@0.5 |")
    w("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in results:
        t, d = r["m_tuned"], r["m_default"]
        w(f"| {r['kind']} | {'sim' if r['include_country'] else 'não'} "
          f"| {r['n_features']} | {r['ti']['pr_auc']} | {r['ti']['roc_auc']} "
          f"| {t['precision']} | {t['recall']} | {t['f1']} | {t['fpr']} "
          f"| {d['precision']} | {d['recall']} |")

    w("\n## Efeito do `country` (quantificação do vazamento — D12)")
    for kind in ["lgbm", "logreg"]:
        a = next(r for r in results if r["kind"] == kind and not r["include_country"])
        b = next(r for r in results if r["kind"] == kind and r["include_country"])
        w(f"- **{kind}**: PR-AUC sem country = {a['ti']['pr_auc']} → "
          f"com country = {b['ti']['pr_auc']} "
          f"(Δ={round(b['ti']['pr_auc']-a['ti']['pr_auc'],4)})")

    w("\n## Recall por attack_class no teste (modelo sem country)")
    for kind in ["lgbm", "logreg"]:
        r = next(x for x in results if x["kind"] == kind and not x["include_country"])
        w(f"- {kind}: {r['recall_by_class']}")

    w("\n## Feature importance — LightGBM (sem country, top 12)")
    r = next(x for x in results if x["kind"] == "lgbm" and not x["include_country"])
    for n, v in r.get("importance", []):
        w(f"- {n}: {v}")

    w("\n## Walk-forward (TimeSeriesSplit) — robustez")
    for (kind, wfres) in wf:
        w(f"- {kind} (sem country): {wfres['folds']} folds | "
          f"PR-AUC {wfres['pr_auc_mean']}±{wfres['pr_auc_std']} | "
          f"F1 {wfres['f1_mean']}±{wfres['f1_std']}")

    w("\n## ⚠️ Caveat — por que o PR-AUC do LightGBM dá ~1,0 (não é 'modelo perfeito')")
    w("- Investigado: `src_endpoint_div20` separa o teste quase perfeitamente "
      "sozinha. Os ataques sintéticos da janela (cred_stuffing/ddos) martelam **um "
      "único endpoint** → diversidade ≈1, enquanto tráfego legítimo navega por "
      "vários. É **separabilidade comportamental trivial do dado sintético**, "
      "NÃO vazamento de identidade (o modelo SEM country também dá 1,0).")
    w("- Em tráfego real, ataques são mais ruidosos → esperar performance menor. "
      "O valor aqui é o **pipeline/metodologia**, não o número.")
    w("- A métrica mais honesta é o **walk-forward**: a variância alta "
      "(F1 0,58±0,41) revela folds com ataques raros/novos (scanner, zero_day) "
      "onde o modelo sofre — o retrato realista sob drift.")

    w("\n## Leitura")
    w("- PR-AUC é a métrica honesta sob desbalanço (ROC-AUC infla). ")
    w("- O Δ com/sem country mede o quanto a identidade 'vaza' o rótulo: no LGBM "
      "Δ≈0 (comportamento já satura); na LogReg +0,10 (o modelo fraco se apoia "
      "no country vazado). Preferimos a versão SEM country por generalizar.")
    w("- Tradeoffs: LightGBM = teto de performance; LogReg = piso edge-friendly "
      "(menor, mais rápido, alvo de distilação na 2.4).")
    return "\n".join(L)


def main() -> None:
    df = load_features()
    results = []
    for kind in ["lgbm", "logreg"]:
        for inc in [False, True]:
            results.append(run_config(df, kind, inc))
    wf = [(k, walk_forward(df, k, include_country=False)) for k in ["lgbm", "logreg"]]
    text = build_report(df, results, wf)
    print(text)
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "2_3_model_report.md").write_text(text, encoding="utf-8")
    print(f"\n[WRITE] reports/2_3_model_report.md + models/*.joblib")


if __name__ == "__main__":
    main()
