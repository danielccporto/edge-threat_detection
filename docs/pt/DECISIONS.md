# Log de Decisões (ADR-lite)

Registro cronológico das decisões de projeto e seu raciocínio. Alimenta o
writeup exigido no entregável ("reasoning for each task").

---

## D1 — Organizar dados em `data/raw/` (imutável) + `data/interim/` (derivado)
**Contexto:** CSVs soltos na raiz. **Decisão:** consolidar sob `data/`, com
`raw/` versionado e imutável e `interim/` para derivados (gitignored).
**Porquê:** separa fonte de verdade de artefatos reproduzíveis; padrão de
projeto de dados.

## D2 — Camada de padronização ANTES do join
**Contexto:** tipos vêm todos como string do CSV; nomes de colunas de tempo
inconsistentes entre tabelas. **Decisão:** criar `src/ingestion` com casting
tipado + validação de contrato antes de qualquer join.
**Porquê:** evita bugs silenciosos de tipo/formato propagando para 2.1-2.4;
falha cedo e alto se o contrato quebrar.

## D3 — Padronização LEVE de nomes
**Decisão:** preservar nomes originais do enunciado; padronizar só colunas de
tempo (`timestamp→event_ts`, `active_from→active_from_ts`, etc.).
**Alternativas:** preservar tudo (convive com inconsistência) / renomear tudo
(afasta do enunciado). **Porquê:** equilíbrio entre limpeza e fidelidade.

## D4 — Saída intermediária em Parquet
**Decisão:** `data/interim/*.parquet`. **Porquê principal:** preserva a tipagem
(datetime UTC, int, categórico ordenado) — CSV voltaria tudo a string.
Secundário: colunar/comprimido, idiomático no ecossistema de ML, escala para o
volume de produção do case. **Tradeoff aceito:** parquet não é inspecionável à
mão → por isso `raw/` continua em CSV legível.

## D5 — Unidade de predição: por-request com features de fonte
**Decisão:** modelo decide por request (encaixa no <5ms do edge), mas usa
features agregadas de IP/JA3/sessão; label propagado da fonte+janela para a
request. **Alternativas:** por-fonte (afasta da unidade de bloqueio no edge) /
ambas. **Porquê:** reconcilia a restrição de edge com o fato de o sinal de
ataque emergir em sequência; conecta com a 3.1 (estado em edge stateless).

## D6 — Join temporal estrito (2.1)
**Decisão:** request é maliciosa só se casar (ip/CIDR/JA3) **e** cair dentro de
`[active_from, active_until]`. Múltiplos matches → classe pela maior confiança
(desempate por severidade). **Porquê:** respeitar os bounds temporais evita
rotular como maliciosa a atividade de uma fonte fora da janela do incidente.

### Descobertas da 2.1 (registradas em reports/2_1_labeling_report.md)
- 592 maliciosas (1,18%) / desbalanço 83:1 na amostra (produção <0,1%).
- 36 incidentes "sem match" investigados → são rótulos **redundantes** (fonte já
  coberta por outro incidente no horário real); zona cinza = 0.
- 24/33 IPs têm múltiplos incidentes (um com 19) → janelas forenses imprecisas;
  deduplicar por fonte antes de análise source-level.
- Natureza Positive-Unlabeled: "benigno" = não-rotulado, não limpo.

## D7 — Split temporal, imbalance só no treino (planejado p/ 2.3)
**Decisão:** separar treino/teste por tempo (sem leakage); tratar desbalanço
(class weights / sampling) **apenas no fold de treino**, nunca antes do split.
**Porquê:** reamostrar antes do split vaza informação e infla métrica; split
temporal simula o cenário real de drift.

---

## D8 — Features de fonte via rolling causal, janela dupla (2.2)
**Decisão:** para cada request, agregar apenas requests **anteriores (causais)**
da mesma fonte em **duas janelas**: temporal (**5 min**) e por contagem
(**últimas 20 requests**). Tamanhos ficam como hiperparâmetros.
**Alternativas descartadas:** agregado global por fonte (vaza futuro, não serve
em tempo real) e sessão por gap (complexo de servir no edge) — ambas viram
menção no writeup.
**Porquê:** única opção que (1) não vaza futuro p/ o split temporal da 2.3,
(2) é computável no edge em tempo real com estado leve por fonte (base da 3.1),
(3) captura tanto burst (5 min) quanto low-and-slow (20 req).

## D9 — Headers via flags + contagens (2.2)
**Decisão (default):** derivar por request flags/contagens
(`has_cookie`, `has_authorization`, `has_referer`, `n_headers`,
`has_content_type`). Não fazer one-hot completo dos valores (alta cardinalidade
e pouco sinal). **Porquê:** leve, interpretável e barato no edge.

## D10 — Modelos: LightGBM (principal) + Regressão Logística (baseline/edge)
**Decisão:** LightGBM raso como modelo principal (acurácia, feature importance,
calibração) e LogReg como piso edge-deployable e alvo de distilação (2.4).
Random Forest e árvore única ficam como menção. **Porquê:** latência não é o
gargalo (todos <5ms); o critério é tamanho/WASM + calibração, onde GBDT raso
domina em acurácia-por-byte e a LR é o mínimo servível.

## D11 — Imbalance: class weights + calibração de threshold (SMOTE só comparação)
**Decisão:** manter a distribuição real; tratar desbalanço com
`scale_pos_weight`/`class_weight='balanced'` **só no fold de treino** + escolha
de limiar pela curva PR/custo (3.3). SMOTE/oversampling só como experimento de
comparação no writeup. **Porquê:** o viés para benigno é problema de THRESHOLD,
não de aprendizado (separação já altíssima); SMOTE fabrica combinações irreais
em features de sequência, derruba precisão e quebra calibração.

## D12 — Excluir features de IDENTIDADE crua; country em teste A/B
**Decisão:** modelo com núcleo **comportamental/agregado**, SEM `source_ip`,
`tls_fingerprint` (JA3) nem `country` crus como preditores. Treinar duas versões
(com e sem `country`) para **quantificar o vazamento**. Identidade entra só como
(a) comportamento derivado (já temos: src_*), (b) classe de cliente, (c)
reputação/threat-intel como sinal SEPARADO (booleano known_bad), não como
categoria que o modelo decora.
**Evidência (data):** JA3 e country são quase-lookup do rótulo (5 JA3 = 100%
malicioso, 4 = 0%; RU/CN/VN/ID = 100%); rótulo foi criado a partir da identidade
(circular); 0/30 IPs maliciosos do teste são novos → métrica com identidade
seria memorização irreal e é o colapso adversarial da 3.4.

## D13 — Split temporal: corte no dia 11 (~72/28) + walk-forward
**Decisão (confirmada):** headline split = treino **06-10/jan**, teste
**11-12/jan** (sem shuffle; pré-proc ajustado só no treino) + **walk-forward
(TimeSeriesSplit)** como validação de robustez/variância.

**Raciocínio-chave (importante):** os ataques são **localizados no tempo** —
cada tipo só ocorre em dias específicos:
`scanner`→07; `credential_stuffing`→07 e 11; `api_abuse`→08-09; `ddos_l7`→09 e
12; `zero_day_exploit`→**só dia 10 (6 casos)**; dia 06 = 100% benigno.
Consequência: **nenhum corte único cobre todos os tipos em treino E teste** — o
que define o trade-off de onde cortar:
- corte 10 (~60/40): teste inclui `zero_day` inédito → mede ataque NOVO, mas
  n=6 e menos treino.
- **corte 11 (~72/28): teste = cred_stuffing + ddos (tipos já vistos), ~240
  positivos → nota estável e justa.** ← escolhido como headline.
- corte 12 (~87/13): teste só `ddos`, 101 positivos → estreito/instável.

Walk-forward recupera o que o corte único perde: cada tipo (scanner, api_abuse,
zero_day) cai no teste em algum fold, e reportamos variância em vez de um número
de sorte. Dia 06 fica no treino (ancora o "normal"); recall no zero_day (dia 10)
reportada à parte como sonda de ataque inédito.

## D14 — Validação crítica revelou limites; modelo final é HÍBRIDO
**Contexto:** bateria de validação (`src/modeling/validate.py`,
reports/2_3_validation.md) mostrou: (T1) regra de 1 linha quase empata o LGBM →
teste sintético trivialmente separável; (T2) label-shuffle → pipeline sem bug;
(T3) fonte nova R≈0,76 → sinal comportamental generaliza; (T4) **supervisionado
cego a ataque novo** (recall≈0 em classe não vista).
**Decisão:** o modelo final NÃO é só supervisionado — é **híbrido**
(`src/modeling/hybrid.py`): LightGBM (ataques conhecidos) **OR** IsolationForest
treinado só em benigno (anomalia/ataque inédito). Fecha a lacuna do T4 e entrega
o que a 3.2 pede.
**Resultado (leave-one-class-out, recall na classe inédita):** super→híbrido:
cred_stuffing 0→0,98; ddos 0,05→0,88; scanner 0→0,92; zero_day 0,33→0,83.
**Exceção honesta:** `api_abuse` segue 0 (mimetiza tráfego legítimo → nem anômalo
nem conhecido); é o low-and-slow/mimicry, trabalho futuro (features de sessão
mais longas). Custo: camada de anomalia orçada em ~1% FPR; ponto de operação
final calibrado por custo na 3.3.

## D15 — Hiperparâmetros por busca leve orientada a edge
**Decisão:** não caçar métrica (tarefa saturada), e sim escolher o **menor
modelo** que segura a performance honesta. Busca em grid pequeno via
TimeSeriesSplit no treino (sem leakage), métrica = PR-AUC médio
(`src/modeling/tune.py`, reports/2_3_tuning.md).
**Escolhido:** LightGBM `n_estimators=120, max_depth=6, num_leaves=15, lr=0.1`
(size-proxy 1800; PR-AUC CV ~0,85 — bem menor que o headline 1,0, confirmando a
trivialidade do teste). Existe opção ainda menor (leaves=7, size 840, PR-AUC
~0,83) guardada p/ o tradeoff de edge na 2.4. IsolationForest fixado em
n_estimators=200. Thresholds NÃO são tunados aqui — vêm da calibração por custo
(3.3).

## D16 — Viabilidade no edge: modelo não é o gargalo; export p/ JS puro (2.4)
**Medições** (`src/deploy/benchmark.py`, reports/2_4_edge.md + 2_4_benchmark.json):
latência single-sample em Python é teto enganoso (overhead de intérprete); o
throughput em lote revela o custo real da aritmética do LightGBM em **~2µs/req**
(538k req/s), 2.500× abaixo dos 5ms. Tamanho: LGBM 213KB, LogReg 6KB.
**Decisão de export:** compilar o modelo para **código sem dependências** via
`m2cgen` (`src/deploy/export_edge.py` → `models/edge/edge_model.js`, 259KB de
if-else puro + `feature_order.json`). Serving: Worker calcula features
per-request inline + lê estado rolling da fonte (KV/Durable Object, caminho
crítico — 3.1) + scoreRequest + anomalia + decisão OR; atualização de modelo =
publicar novo artefato (retreino central, liga com drift/3.2). **Gargalo real =
estado das features de fonte (3.1) + calibração de limiar (3.3), não inferência.**
Modelo final = **híbrido LightGBM + IsolationForest** (LogReg NÃO entra; aparece
só como referência de escala). Como as medições dão folga enorme, **não há
simplificação necessária**; contingências registradas: variante LGBM ~2× menor
(preferida) ou score estatístico no lugar do IsolationForest.

---
# Parte 3 — Deep-dives (writeups em reports/3_x_*.md)

## D17 — Estado no edge: agregado + Durable Objects + degradação graciosa (3.1)
**Veredito** (reports/3_1_stateful_edge.md): manter contexto de sessão num edge
stateless é viável guardando **estado agregado por fonte** (EWMA/ring buffer/HLL,
~centenas de bytes, update O(1)), com **roteamento sticky por chave → Durable
Object** único por fonte, cache local do PoP e **write-behind**. Gargalo do
orçamento = **1 leitura de estado (~ms)**; modelo ~2µs é desprezível. Se o store
cair: **degradação graciosa** — modelo de fallback só com features per-request
(a separação de features já habilita), anomalia/reputação locais, e **fail-open
nos fluxos de pagamento** (FP caro) com rate-limit grosseiro.

## D18 — Threshold por custo, dinâmico e calibrado (3.3)
**Veredito** (reports/3_3_threshold_economics.md): limiar ótimo não é número fixo,
é `q* = C_FP/(C_FP+C_FN)` sobre probabilidade **calibrada**. Baseline (FP $2,50 /
FN $0,10) → **q*=0,962** (bloquear só com ~96% certeza; FP 25× FN; upside do ML só
~$5k/dia → foco é não gerar FP). Campanha (FN $5,00) → **q*=0,333** (agressivo;
upside ~$250k/dia). Requer calibração (Platt/isotonic) + **limiar dinâmico por
regime** (chavear C_FN ao detectar campanha) + **condicional a endpoint** ($2,50
só vale no checkout). Valores de custo são do enunciado; math e conclusões nossas.
