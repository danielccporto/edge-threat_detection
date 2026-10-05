# 2.3 — Relatório do Modelo Baseline

- Split temporal (corte 11/jan): treino=35984 (353 mal) | teste=14016 (239 mal) [28% teste]
- Imbalance: `class_weight='balanced'` só no treino. Limiar 'tuned' = F1-ótimo escolhido no TREINO e aplicado ao teste (threshold livre de leakage; calibração por custo fica na 3.3).

## Métricas no teste (11-12/jan)

| Modelo | country | feats | PR-AUC | ROC-AUC | P@tuned | R@tuned | F1@tuned | FPR@tuned | P@0.5 | R@0.5 |
|---|---|---|---|---|---|---|---|---|---|---|
| lgbm | não | 35 | 1.0 | 1.0 | 1.0 | 0.9582 | 0.9786 | 0.0 | 1.0 | 1.0 |
| lgbm | sim | 36 | 1.0 | 1.0 | 1.0 | 0.9623 | 0.9808 | 0.0 | 1.0 | 1.0 |
| logreg | não | 35 | 0.8597 | 0.9918 | 1.0 | 0.5063 | 0.6722 | 0.0 | 1.0 | 0.5732 |
| logreg | sim | 36 | 0.9611 | 0.9988 | 1.0 | 0.5983 | 0.7487 | 0.0 | 1.0 | 0.728 |

## Efeito do `country` (quantificação do vazamento — D12)
- **lgbm**: PR-AUC sem country = 1.0 → com country = 1.0 (Δ=0.0)
- **logreg**: PR-AUC sem country = 0.8597 → com country = 0.9611 (Δ=0.1014)

## Recall por attack_class no teste (modelo sem country)
- lgbm: {'credential_stuffing': 1.0, 'ddos_l7': 0.901}
- logreg: {'credential_stuffing': 0.341, 'ddos_l7': 0.733}

## Feature importance — LightGBM (sem country, top 12)
- response_time_ms: 293
- body_size_bytes: 267
- src_err_rate20: 154
- src_cnt20: 136
- src_endpoint_div20: 117
- src_cv_interarrival20: 90
- ua_len: 88
- n_headers: 79
- hour: 74
- ua_non_browser: 71
- has_authorization: 53
- path_len: 40

## Walk-forward (TimeSeriesSplit) — robustez
- lgbm (sem country): 4 folds | PR-AUC 0.9214±0.0791 | F1 0.5653±0.4209
- logreg (sem country): 4 folds | PR-AUC 0.7307±0.2121 | F1 0.4993±0.3213

## ⚠️ Caveat — por que o PR-AUC do LightGBM dá ~1,0 (não é 'modelo perfeito')
- Investigado: `src_endpoint_div20` separa o teste quase perfeitamente sozinha. Os ataques sintéticos da janela (cred_stuffing/ddos) martelam **um único endpoint** → diversidade ≈1, enquanto tráfego legítimo navega por vários. É **separabilidade comportamental trivial do dado sintético**, NÃO vazamento de identidade (o modelo SEM country também dá 1,0).
- Em tráfego real, ataques são mais ruidosos → esperar performance menor. O valor aqui é o **pipeline/metodologia**, não o número.
- A métrica mais honesta é o **walk-forward**: a variância alta (F1 0,58±0,41) revela folds com ataques raros/novos (scanner, zero_day) onde o modelo sofre — o retrato realista sob drift.

## Leitura
- PR-AUC é a métrica honesta sob desbalanço (ROC-AUC infla). 
- O Δ com/sem country mede o quanto a identidade 'vaza' o rótulo: no LGBM Δ≈0 (comportamento já satura); na LogReg +0,10 (o modelo fraco se apoia no country vazado). Preferimos a versão SEM country por generalizar.
- Tradeoffs: LightGBM = teto de performance; LogReg = piso edge-friendly (menor, mais rápido, alvo de distilação na 2.4).