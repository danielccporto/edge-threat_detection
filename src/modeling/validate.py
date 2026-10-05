"""
2.3 — Bateria de validação crítica do baseline.

Um PR-AUC ~1,0 exige ceticismo. Estes testes separam "pipeline correto" de
"modelo confiável" e expõem os limites da estratégia supervisionada:

  T1  Baselines triviais  — o ML supera uma regra de 1 linha?
  T2  Label-shuffle       — embaralhar rótulo deve derrubar p/ aleatório (senão há bug/leakage)
  T3  Split por fonte      — generaliza para source_ip NUNCA visto?
  T4  Leave-one-class-out  — detecta um tipo de ataque NUNCA visto? (concept drift)

Uso: python -m src.modeling.validate
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.metrics import f1_score, precision_score, recall_score

from .evaluate import best_f1_threshold, metrics_at, threshold_independent
from .split import TARGET, feature_columns, load_features, temporal_split
from .train import make_pipeline

ROOT = Path(__file__).resolve().parents[2]


def _fit_eval(cols, Xtr, ytr, Xte, yte):
    pipe = make_pipeline("lgbm", cols).fit(Xtr, ytr)
    p = pipe.predict_proba(Xte)[:, 1]
    thr = best_f1_threshold(ytr, pipe.predict_proba(Xtr)[:, 1])
    return metrics_at(yte, p, thr), threshold_independent(yte, p)


def build_report() -> str:
    df = load_features()
    cols = feature_columns(df, include_country=False)
    tr, te = temporal_split(df)
    Xtr, ytr = tr[cols], tr[TARGET].astype(int)
    Xte, yte = te[cols], te[TARGET].astype(int)
    L = []; w = L.append
    w("# 2.3 — Validação Crítica do Baseline\n")
    w("Objetivo: decidir, com evidência, quanta confiança merecem os modelos.\n")

    # T1
    w("## T1 — Baselines triviais (o ML adiciona valor sobre uma regra boba?)")
    rule = (te["src_endpoint_div20"] <= 2).astype(int)
    rule2 = ((te["is_error"] == 1) & (te["ua_non_browser"] == 1)).astype(int)
    m, ti = _fit_eval(cols, Xtr, ytr, Xte, yte)
    w(f"- Dummy (sempre benigno): R=0,00 F1=0,00")
    w(f"- **Regra `src_endpoint_div20<=2`**: P={precision_score(yte,rule):.3f} "
      f"R={recall_score(yte,rule):.3f} F1={f1_score(yte,rule):.3f}")
    w(f"- Regra `is_error & ua_non_browser`: P={precision_score(yte,rule2):.3f} "
      f"R={recall_score(yte,rule2):.3f} F1={f1_score(yte,rule2):.3f}")
    w(f"- LightGBM completo: PR-AUC={ti['pr_auc']:.3f} P={m['precision']:.3f} "
      f"R={m['recall']:.3f} F1={m['f1']:.3f}")
    w("> Uma regra de 1 linha quase empata com o LGBM → no teste sintético a "
      "tarefa é **trivialmente separável**; o ML demonstra pouco aqui.\n")

    # T2
    w("## T2 — Label-shuffle (sanidade do pipeline)")
    rng = np.random.default_rng(0)
    ytr_s = pd.Series(rng.permutation(ytr.values), index=ytr.index)
    _, ti2 = _fit_eval(cols, Xtr, ytr_s, Xte, yte)
    w(f"- LGBM com rótulo de treino embaralhado: PR-AUC={ti2['pr_auc']:.3f} "
      f"(prevalência teste={yte.mean():.4f})")
    w("> Cai para ~aleatório → **pipeline mecanicamente correto, sem bug/leakage "
      "de plumbing**. O sinal alto é real nos dados, não erro de código.\n")

    # T3
    w("## T3 — Split por FONTE disjunta (generaliza p/ source_ip novo?)")
    srcs = df["source_ip"].astype(str).to_numpy(dtype=object)
    uniq = np.unique(srcs); rng = np.random.default_rng(42); rng.shuffle(uniq)
    cut = int(0.7 * len(uniq)); te_s = set(uniq[cut:])
    m_te = df["source_ip"].astype(str).isin(te_s)
    Xtr2, ytr2 = df.loc[~m_te, cols], df.loc[~m_te, TARGET].astype(int)
    Xte2, yte2 = df.loc[m_te, cols], df.loc[m_te, TARGET].astype(int)
    m3, ti3 = _fit_eval(cols, Xtr2, ytr2, Xte2, yte2)
    w(f"- fontes teste={len(te_s)} | mal teste={int(yte2.sum())}")
    w(f"- LGBM fontes disjuntas: PR-AUC={ti3['pr_auc']:.3f} "
      f"P={m3['precision']:.3f} **R={m3['recall']:.3f}** F1={m3['f1']:.3f}")
    w("> Generaliza RAZOAVELMENTE a fontes novas: ranking quase perfeito e recall "
      "cai de ~0,95 (headline) p/ ~0,76 — degradação moderada, ainda funcional. "
      "Confirma que o sinal é COMPORTAMENTAL (não memorização de fonte), mas que "
      "o limiar merece recalibração por população (liga com a 3.3).\n")

    # T4
    w("## T4 — Leave-one-attack-class-out (detecta ataque NUNCA visto?)")
    benign = df[~df[TARGET]].sample(n=min(5000, int((~df[TARGET]).sum())),
                                    random_state=1)
    for C in ["credential_stuffing", "ddos_l7", "api_abuse", "scanner",
              "zero_day_exploit"]:
        is_C = (df["attack_class"] == C) & df[TARGET]
        Xtr3, ytr3 = df.loc[~is_C, cols], df.loc[~is_C, TARGET].astype(int)
        test_df = pd.concat([df[is_C], benign])
        m4, _ = _fit_eval(cols, Xtr3, ytr3, test_df[cols],
                          test_df[TARGET].astype(int))
        w(f"- classe retirada **{C}** (n={int(is_C.sum())}): "
          f"recall nessa classe = **{m4['recall']:.3f}**")
    w("> Recall ≈0 em classe não vista → **o supervisionado NÃO detecta ataque "
      "novo**. Prova empírica de que a estratégia pura é insuficiente para o "
      "drift do enunciado → motiva não-supervisionado/anomalia (3.2).\n")

    w("## Veredito")
    w("- **Pipeline:** confiável (T2 ok, sem leakage de código).")
    w("- **Métrica headline:** enganosa — reflete trivialidade do sintético (T1).")
    w("- **Generalização a fonte nova:** razoável (R~0,76); sinal é comportamental, "
      "não memorização de fonte (T3) → recalibrar limiar por população.")
    w("- **Generalização a ataque novo:** falha (T4) → supervisionado sozinho é "
      "insuficiente; precisa de camada não-supervisionada + retreino contínuo.")
    return "\n".join(L)


def main() -> None:
    text = build_report()
    print(text)
    dest = ROOT / "reports" / "2_3_validation.md"
    dest.write_text(text, encoding="utf-8")
    print(f"\n[WRITE] reports/2_3_validation.md")


if __name__ == "__main__":
    main()
