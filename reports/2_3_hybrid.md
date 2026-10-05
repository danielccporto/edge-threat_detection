# 2.3+ — Modelo Híbrido (LightGBM + IsolationForest)

- Orçamento de FPR da camada de anomalia: 1% do benigno.
- Regra: bloquear se `p_super >= 1.000` OU `anomalia >= 0.599`.

## Teste headline (11-12/jan) — cada camada e o híbrido
- Supervisionado só: P=1.0 R=0.958 F1=0.979 FPR=0.0
- Anomalia só: P=0.72 R=0.925 F1=0.81 FPR=0.00624
- **Híbrido (OR)**: P=0.733 R=0.987 F1=0.841 FPR=0.00624

## Prova no leave-one-class-out: supervisionado vs híbrido (recall na classe inédita)
| classe retirada do treino supervisionado | recall SUPER só | recall HÍBRIDO |
|---|---|---|
| credential_stuffing (n=249) | 0.0 | **0.98** |
| ddos_l7 (n=247) | 0.012 | **0.883** |
| api_abuse (n=65) | 0.0 | **0.0** |
| scanner (n=25) | 0.0 | **0.92** |
| zero_day_exploit (n=6) | 0.0 | **0.667** |

## Leitura
- O supervisionado sozinho zera (ou quase) a recall em classe não vista; o **híbrido recupera 4 de 5** (cred_stuffing, ddos, scanner, zero_day) via camada de anomalia — fecha a lacuna do T4.
- **Exceção honesta — `api_abuse` continua 0.** Ele **mimetiza tráfego legítimo** (sem rajada, sem erros, endpoints normais) → não é 'anômalo' o suficiente para o IsolationForest nem conhecido pelo supervisionado. É o ataque low-and-slow/mimicry, o mais difícil; exige features de sequência mais longas e/ou detecção por comportamento de sessão (trabalho futuro, liga com 3.4).
- Custo: a camada de anomalia adiciona FPR (orçado aqui em 1%); o ponto de operação final é calibrado pela economia de custo na 3.3.
- Edge: IsolationForest é leve (árvores rasas, sem GPU) e servível no WASM junto ao supervisionado (ver 2.4).