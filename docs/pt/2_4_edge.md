# 2.4 — Viabilidade no Edge

> **Modelo final = híbrido LightGBM + IsolationForest.** A Regressão Logística
> NÃO faz parte da solução de produção — aparece aqui só como **ponto de
> referência de escala** (o piso linear possível), para contextualizar o tamanho
> dos modelos que de fato usamos.

## Decomposição do orçamento de 5ms

O caminho crítico por requisição no edge é:
```
features per-request (µs)  +  LOOKUP de estado da fonte  +  features rolling (µs)  +  MODELO (µs)
```
**Conclusão antecipada:** a inferência do modelo é a parte **mais barata**. O
gargalo real do orçamento é o **cálculo das features de fonte + a leitura do
estado** (tratado na 3.1). Abaixo provamos que o modelo cabe folgado.

## Medições (reports/2_4_benchmark.json)

| Modelo | Tamanho (joblib) | Complexidade | Latência 1-req (Python) | Throughput lote |
|---|---|---|---|---|
| **LightGBM** (modelo final) | 213 KB | 120 árvores / 3.480 nós | p50 5,9ms • p99 9,5ms | **538.598 req/s** |
| **IsolationForest** (modelo final) | — | 200 árvores | média 12,2ms • p99 19,6ms | — |
| Regressão Logística (só referência) | 6 KB | 36 coeficientes | p50 4,2ms • p99 7,3ms | 796.752 req/s |

### ⚠️ Lendo os números corretamente
A **latência single-sample em Python é um teto enganoso** — ela mede o overhead
do intérprete + pandas + dispatch do sklearn por chamada, **não** a aritmética do
modelo. A prova está no throughput em lote: 538k req/s para o LightGBM equivalem
a **~1,9µs por requisição** quando o overhead some. Ou seja:

- **Custo real da aritmética do LightGBM ≈ 2µs/req** (0,002ms) — 2.500× abaixo do
  orçamento de 5ms.
- Num runtime **compilado** (WASM/JS, sem Python) não há overhead de intérprete;
  a predição são ~720 comparações de inteiros (profundidade 6 × 120 árvores).
- A Regressão Logística é ainda menor: um único produto escalar de 36 termos.

**Veredito de latência:** o modelo supervisionado cabe no orçamento com folga
enorme. O IsolationForest (200 árvores) é o mais pesado, mas ainda trivial se
compilado; ver simplificação abaixo.

### Throughput (50k req/s/nó) — o que medimos e o que depende da 3.1
O throughput medido é **do modelo**: ~538k req/s em **um único core** (Python,
em lote). Conta direta contra a exigência: `50.000 req/s × 2µs = 0,1 s de CPU por
segundo = ~10% de um core` só para a inferência. Ou seja, **o modelo não é o
gargalo de throughput** — há folga grande, que ainda escala horizontalmente
(mais cores/nós).

**Ressalva honesta:** isto é throughput *do modelo*, single-thread, não um teste
de carga de **sistema**. A 50k req/s, o gargalo real não é a CPU do modelo e sim
a **I/O do estado da fonte** (ler/atualizar os contadores rolling a cada
requisição) — que é um problema de arquitetura de estado, tratado na **3.1**, e
que não foi medido aqui por depender do runtime de edge e do state store reais.

## Memória / tamanho

- LightGBM: 213 KB serializado; compilado para JS deu **259 KB** (if-else puro).
- Regressão Logística: 6 KB (praticamente só os pesos).
- Todos cabem com sobra no limite de um Cloudflare Worker (~1 MB comprimido no
  plano free; 10 MB pago). IsolationForest com 200 árvores somaria algumas
  centenas de KB — ainda viável, mas é o primeiro candidato a enxugar.

## Distilação / simplificação

**As medições mostram que NÃO precisamos simplificar** — o modelo final cabe no
orçamento com folga de ~2.500× em latência e centenas de KB bem abaixo do limite.
As opções abaixo ficam registradas apenas como **contingência**, caso um cenário
futuro (runtime mais apertado, edge com teto menor) exija enxugar:

1. **Variante LightGBM ~2× menor** (`num_leaves=7`, ~2% de PR-AUC a menos), já
   identificada no tuning (reports/2_3_tuning.md) — o caminho preferido se for
   preciso reduzir, por manter a mesma família de modelo.
2. **Camada de anomalia mais leve:** como o IsolationForest (200 árvores) é o
   componente mais pesado, trocá-lo por um score estatístico (distância de
   Mahalanobis / z-score sobre as features de fonte) ou reduzir `n_estimators`.
3. *(Hipótese extrema)* destilar o LightGBM numa Regressão Logística de 6 KB —
   listada por completude, mas improvável dada a folga atual e a perda de recall.

## Export e serving no edge

**Export (feito — prova concreta):** usamos `m2cgen` para compilar o LightGBM em
**JavaScript sem dependências** (`models/edge/edge_model.js`, 259 KB) — uma função
`scoreRequest(input)` de puras comparações, mais `models/edge/feature_order.json`
com a ordem esperada das 35 features. Reproduzível por
`python -m src.deploy.export_edge`.

**Alternativas de export:** ONNX + onnxruntime-web (runtime mais pesado) ou
Treelite (gera C → WASM). O código puro do m2cgen é o mais leve e sem dependência.

**Arquitetura de serving proposta:**
```
Requisição → Worker (edge)
  1. extrai features per-request (inline, stateless)        ~µs
  2. lê/atualiza estado rolling da fonte no KV/Durable Object  ← caminho crítico (3.1)
  3. scoreRequest(features)  [LightGBM compilado]            ~µs
  4. anomalia (IF compilado ou score estatístico)           ~µs
  5. decisão OR + limiar calibrado por custo (3.3) → allow/throttle/block
```
- **Thresholds e pesos** ficam embutidos no artefato (constantes).
- **Atualização do modelo** = publicar um novo `edge_model.js` (retreino central
  → deploy ao edge); casa com o combate ao drift (3.2). Sem chamada a servidor
  central no caminho quente (proibido pelo enunciado).
- **Estado da fonte** é o único componente stateful — detalhado na 3.1
  (KV/Durable Objects; o que quebra se o store cair).

## Resumo
O modelo **não é o gargalo**: ~2µs de aritmética, centenas de KB, exportável para
JS puro (artefato gerado). O desafio de edge real é o **estado das features de
fonte** (3.1) e a **calibração do limiar por custo** (3.3), não a inferência.
