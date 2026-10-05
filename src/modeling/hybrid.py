"""
2.3+ — Modelo híbrido: supervisionado (LightGBM) + anomalia (IsolationForest).

Motivação (provada em validate.py / T4): o supervisionado é cego a ataque novo.
O IsolationForest, treinado SÓ em tráfego benigno, sinaliza desvios do normal e
cobre o inédito. Decisão final (OR):

    bloqueia  se   p_super >= thr_super   OU   score_anomalia >= thr_anom

- thr_super: F1-ótimo escolhido no treino (sem leakage).
- thr_anom: quantil do score de anomalia no benigno de treino p/ um orçamento
  de FPR da camada de anomalia (default 1%).

Demonstra em leave-one-class-out que o híbrido recupera recall que o
supervisionado zera. Saída: reports/2_3_hybrid.md
Uso: python -m src.modeling.hybrid
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import confusion_matrix

from .evaluate import best_f1_threshold
from .split import TARGET, feature_columns, load_features, temporal_split
from .train import make_pipeline

ROOT = Path(__file__).resolve().parents[2]
ANOM_FPR_BUDGET = 0.01  # 1% do benigno pode ser flagado pela camada de anomalia


def _pr_f1_fpr(y_true, y_pred) -> dict:
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    return {"precision": round(p, 3), "recall": round(r, 3),
            "f1": round(f1, 3), "fpr": round(fpr, 5)}


def fit_hybrid(train_df, cols):
    ytr = train_df[TARGET].astype(int)
    # supervisionado
    sup = make_pipeline("lgbm", cols).fit(train_df[cols], ytr)
    thr_super = best_f1_threshold(ytr, sup.predict_proba(train_df[cols])[:, 1])
    # anomalia: treina SÓ no benigno
    benign = train_df[~train_df[TARGET]]
    iso = IsolationForest(n_estimators=200, random_state=42, n_jobs=-1)
    iso.fit(benign[cols])
    anom_benign = -iso.score_samples(benign[cols])  # maior = mais anômalo
    thr_anom = float(np.quantile(anom_benign, 1 - ANOM_FPR_BUDGET))
    return sup, thr_super, iso, thr_anom


def predict_parts(sup, thr_super, iso, thr_anom, X):
    p_sup = sup.predict_proba(X)[:, 1]
    anom = -iso.score_samples(X)
    sup_flag = (p_sup >= thr_super).astype(int)
    anom_flag = (anom >= thr_anom).astype(int)
    hybrid = ((sup_flag == 1) | (anom_flag == 1)).astype(int)
    return sup_flag, anom_flag, hybrid


def build_report() -> str:
    df = load_features()
    cols = feature_columns(df, include_country=False)
    tr, te = temporal_split(df)
    yte = te[TARGET].astype(int)
    sup, thr_super, iso, thr_anom = fit_hybrid(tr, cols)
    sup_f, anom_f, hyb_f = predict_parts(sup, thr_super, iso, thr_anom, te[cols])

    L = []; w = L.append
    w("# 2.3+ — Modelo Híbrido (LightGBM + IsolationForest)\n")
    w(f"- Orçamento de FPR da camada de anomalia: {ANOM_FPR_BUDGET:.0%} do benigno.")
    w(f"- Regra: bloquear se `p_super >= {thr_super:.3f}` OU "
      f"`anomalia >= {thr_anom:.3f}`.\n")

    w("## Teste headline (11-12/jan) — cada camada e o híbrido")
    for name, pred in [("Supervisionado só", sup_f),
                       ("Anomalia só", anom_f),
                       ("**Híbrido (OR)**", hyb_f)]:
        m = _pr_f1_fpr(yte, pred)
        w(f"- {name}: P={m['precision']} R={m['recall']} F1={m['f1']} "
          f"FPR={m['fpr']}")
    w("")

    w("## Prova no leave-one-class-out: supervisionado vs híbrido (recall na classe inédita)")
    w("| classe retirada do treino supervisionado | recall SUPER só | recall HÍBRIDO |")
    w("|---|---|---|")
    benign_pool = df[~df[TARGET]].sample(n=min(5000, int((~df[TARGET]).sum())),
                                         random_state=1)
    for C in ["credential_stuffing", "ddos_l7", "api_abuse", "scanner",
              "zero_day_exploit"]:
        is_C = (df["attack_class"] == C) & df[TARGET]
        train_sup = df[~is_C]
        # supervisionado SEM a classe C; IF treina em benigno (sempre)
        s, ts, iso2, ta = fit_hybrid(train_sup, cols)
        test_df = pd.concat([df[is_C], benign_pool])
        yt = test_df[TARGET].astype(int)
        sf, af, hf = predict_parts(s, ts, iso2, ta, test_df[cols])
        r_sup = _pr_f1_fpr(yt, sf)["recall"]
        r_hyb = _pr_f1_fpr(yt, hf)["recall"]
        w(f"| {C} (n={int(is_C.sum())}) | {r_sup} | **{r_hyb}** |")

    w("\n## Leitura")
    w("- O supervisionado sozinho zera (ou quase) a recall em classe não vista; "
      "o **híbrido recupera 4 de 5** (cred_stuffing, ddos, scanner, zero_day) "
      "via camada de anomalia — fecha a lacuna do T4.")
    w("- **Exceção honesta — `api_abuse` continua 0.** Ele **mimetiza tráfego "
      "legítimo** (sem rajada, sem erros, endpoints normais) → não é 'anômalo' o "
      "suficiente para o IsolationForest nem conhecido pelo supervisionado. É o "
      "ataque low-and-slow/mimicry, o mais difícil; exige features de sequência "
      "mais longas e/ou detecção por comportamento de sessão (trabalho futuro, "
      "liga com 3.4).")
    w("- Custo: a camada de anomalia adiciona FPR (orçado aqui em 1%); o ponto "
      "de operação final é calibrado pela economia de custo na 3.3.")
    w("- Edge: IsolationForest é leve (árvores rasas, sem GPU) e servível no "
      "WASM junto ao supervisionado (ver 2.4).")
    return "\n".join(L)


def main() -> None:
    text = build_report()
    print(text)
    (ROOT / "reports" / "2_3_hybrid.md").write_text(text, encoding="utf-8")
    print("\n[WRITE] reports/2_3_hybrid.md")


if __name__ == "__main__":
    main()
