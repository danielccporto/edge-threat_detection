# 2.3 — Validação Crítica do Baseline

Objetivo: decidir, com evidência, quanta confiança merecem os modelos.

## T1 — Baselines triviais (o ML adiciona valor sobre uma regra boba?)
- Dummy (sempre benigno): R=0,00 F1=0,00
- **Regra `src_endpoint_div20<=2`**: P=0.919 R=1.000 F1=0.958
- Regra `is_error & ua_non_browser`: P=0.468 R=0.603 F1=0.527
- LightGBM completo: PR-AUC=1.000 P=1.000 R=0.958 F1=0.979
> Uma regra de 1 linha quase empata com o LGBM → no teste sintético a tarefa é **trivialmente separável**; o ML demonstra pouco aqui.

## T2 — Label-shuffle (sanidade do pipeline)
- LGBM com rótulo de treino embaralhado: PR-AUC=0.009 (prevalência teste=0.0171)
> Cai para ~aleatório → **pipeline mecanicamente correto, sem bug/leakage de plumbing**. O sinal alto é real nos dados, não erro de código.

## T3 — Split por FONTE disjunta (generaliza p/ source_ip novo?)
- fontes teste=406 | mal teste=110
- LGBM fontes disjuntas: PR-AUC=0.980 P=1.000 **R=0.754** F1=0.860
> Generaliza RAZOAVELMENTE a fontes novas: ranking quase perfeito e recall cai de ~0,95 (headline) p/ ~0,76 — degradação moderada, ainda funcional. Confirma que o sinal é COMPORTAMENTAL (não memorização de fonte), mas que o limiar merece recalibração por população (liga com a 3.3).

## T4 — Leave-one-attack-class-out (detecta ataque NUNCA visto?)
- classe retirada **credential_stuffing** (n=249): recall nessa classe = **0.000**
- classe retirada **ddos_l7** (n=247): recall nessa classe = **0.012**
- classe retirada **api_abuse** (n=65): recall nessa classe = **0.000**
- classe retirada **scanner** (n=25): recall nessa classe = **0.000**
- classe retirada **zero_day_exploit** (n=6): recall nessa classe = **0.000**
> Recall ≈0 em classe não vista → **o supervisionado NÃO detecta ataque novo**. Prova empírica de que a estratégia pura é insuficiente para o drift do enunciado → motiva não-supervisionado/anomalia (3.2).

## Veredito
- **Pipeline:** confiável (T2 ok, sem leakage de código).
- **Métrica headline:** enganosa — reflete trivialidade do sintético (T1).
- **Generalização a fonte nova:** razoável (R~0,76); sinal é comportamental, não memorização de fonte (T3) → recalibrar limiar por população.
- **Generalização a ataque novo:** falha (T4) → supervisionado sozinho é insuficiente; precisa de camada não-supervisionada + retreino contínuo.