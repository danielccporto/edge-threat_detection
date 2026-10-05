# 2.2 — Catálogo de Features e Justificativa

Pipeline: `src/features/build_features.py` → `data/interim/features.parquet`
(50.000 linhas × 35 features). Duas famílias (ver decisões D8/D9).

## A. Per-request (sem estado — calculáveis no edge isoladamente)

| Feature | O que é | Por quê |
|---|---|---|
| `path_len`, `path_depth`, `n_query_params`, `path_entropy` | características da URL | paths anômalos / fuzzing de scanner |
| `is_sensitive_ep` | bate em /auth/login, /cards/tokenize... | alvos de credential stuffing / card testing |
| `status_code`, `status_class`, `is_error`, `is_429` | resposta | ataques geram muito 401/403/404/429 |
| `response_time_ms`, `body_size_bytes` | tamanho/latência | bots enviam corpos mínimos/uniformes |
| `method_*` (6 flags) | verbo HTTP | padrões por tipo de ataque (ex.: POST em login) |
| `ua_non_browser`, `ua_len` | user-agent | clients `python-requests`/`axios`/`curl` = automação |
| `hour` | hora do dia | sazonalidade do tráfego legítimo |

## B. Headers (flags + contagens — D9)

`n_headers`, `has_cookie`, `has_authorization`, `has_referer`,
`has_content_type`, `has_accept_language`. Bots tendem a mandar **poucos
headers** e sem `Referer`/`Accept-Language` coerentes.

## C. De fonte — rolling CAUSAL por `source_ip` (D8)

Janela dupla: temporal (5 min) e contagem (últimas 20 req). Agregam só o
passado da mesma fonte (sem leakage; servível no edge em tempo real).

| Feature | Sinal |
|---|---|
| `src_cnt_5min`, `src_rate_5min` | volume/rajada (ddos, brute force) |
| `src_cnt20` | atividade recente |
| `src_err_rate20`, `src_err_rate_5min` | fração de erros — **enumeração/credential stuffing** |
| `src_endpoint_div20` | diversidade de endpoints — ataque foca poucos |
| `src_status_div20` | diversidade de status |
| `src_post_ratio_5min` | proporção de POST |
| `src_cv_interarrival20` | regularidade de timing (coef. variação dos intervalos) |

## Poder preditivo — evidência empírica (AUC univariado)

Cada feature isolada vs. `is_malicious` (poder absoluto = max(AUC, 1−AUC);
AUC<0,5 = relação inversa). Top features:

| Feature | AUC | Poder | Direção |
|---|---|---|---|
| `src_err_rate20` | 0,911 | **0,911** | ↑ erro → malicioso |
| `src_endpoint_div20` | 0,126 | **0,874** | ↓ diversidade → malicioso |
| `src_err_rate_5min` | 0,870 | 0,870 | ↑ |
| `status_class` / `is_error` / `status_code` | ~0,85 | ~0,85 | ↑ erro |
| `n_headers` | 0,162 | 0,838 | ↓ headers → malicioso |
| `body_size_bytes` | 0,211 | 0,789 | ↓ corpo → malicioso |
| `ua_non_browser` | 0,755 | 0,755 | ↑ automação |
| `src_rate_5min` / `src_cnt_5min` | 0,747 | 0,747 | ↑ volume |

**Conclusão (responde à 2.2):** as features de **maior poder** são as
**agregadas de fonte** (taxa de erro, diversidade de endpoints, volume) + sinais
de automação (UA não-browser, poucos headers, corpo pequeno). Confirma a
hipótese: o sinal de ataque emerge no **comportamento da sequência**, não na
request isolada — justamente o que motiva a janela rolling causal.

**Observação relevante p/ 3.4 (robustez adversarial):**
`src_cv_interarrival20` teve poder baixo (0,56) nesta amostra — timing não é
discriminador forte aqui, e um atacante que adiciona jitter degrada pouco um
modelo que não depende dele. Diversificar as features (não concentrar em
timing/JA3) é defesa estrutural.
