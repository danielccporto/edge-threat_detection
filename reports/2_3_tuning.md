# 2.3 — Tuning leve do LightGBM (orientado a edge)

- Validação: TimeSeriesSplit(4) no treino; métrica = PR-AUC médio.
- Melhor PR-AUC na busca: **0.8523**; tolerância: 0.01.
- Regra: menor modelo (n_estimators×num_leaves) dentro da tolerância.

## Config escolhida
```
{'n_estimators': 120, 'max_depth': 6, 'num_leaves': 15, 'learning_rate': 0.1}
PR-AUC=0.8523  size(proxy)=1800
```

## Top 8 por PR-AUC (e seus tamanhos)
| n_est | depth | leaves | lr | PR-AUC | size |
|---|---|---|---|---|---|
| 120 | 6 | 15 | 0.1 | 0.8523 | 1800 |
| 120 | 6 | 31 | 0.1 | 0.8486 | 3720 |
| 120 | 6 | 7 | 0.1 | 0.8299 | 840 |
| 200 | 6 | 7 | 0.05 | 0.8213 | 1400 |
| 120 | 6 | 7 | 0.05 | 0.8182 | 840 |
| 120 | 4 | 15 | 0.1 | 0.8154 | 1800 |
| 200 | 3 | 7 | 0.1 | 0.8069 | 1400 |
| 120 | 4 | 7 | 0.1 | 0.7993 | 840 |

## Menores modelos dentro da tolerância
- size=1800 (n_est=120, depth=6, leaves=15, lr=0.1) → PR-AUC=0.8523
- size=3720 (n_est=120, depth=6, leaves=31, lr=0.1) → PR-AUC=0.8486

> Escolhemos o modelo mais enxuto que não perde performance honesta — insumo direto para a viabilidade de edge (2.4).