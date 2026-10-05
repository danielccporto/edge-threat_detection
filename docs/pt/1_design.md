# Parte 1 — Design Ponta a Ponta

Como projetar, treinar e implantar um sistema de ML para detectar tráfego HTTP
malicioso no edge. Esta é a visão de processo completa; os detalhes e números de
cada etapa estão nos relatórios referenciados (2.x e 3.x).

---

## 0. Premissas explícitas (onde o enunciado é ambíguo)
- **Unidade de decisão = requisição**, enriquecida com contexto de fonte. Encaixa
  no bloqueio em tempo real do edge sem abrir mão do sinal de sequência.
- **"Benigno" = não-rotulado**, não "comprovadamente limpo" (Positive-Unlabeled).
- **Prevalência real <0,1%** (a amostra tem 1,18% por amplificação sintética); a
  calibração assume a prevalência de produção.
- **Threat-intel feed** cobre ~30% dos ataques (não veio como dado) → entra como
  feature de **reputação**, sinal separado e que degrada graciosamente.
- **Custo:** FP em pagamento = $2,50; FN = $0,10 (valores do enunciado, 3.3).
- **Runtime:** Cloudflare Workers / WASM, sem GPU, com KV/Durable Objects p/ estado.

## 1. Tratamento de dados
Três fontes: log de requisições (fato), headers (1:N) e rótulos de incidente
(por fonte + janela). Pipeline:
1. **Padronização/ingestão** (`src/ingestion`): casting tipado + contrato de
   schema validado (PK, nulos, domínios), saída em Parquet. Falha cedo se o
   contrato quebrar.
2. **Rotulagem por join temporal** (`src/labeling`, 2.1): requisição é maliciosa
   se casa (IP exato / CIDR / JA3) **e** cai em `[active_from, active_until]`.
   Resultado: 592 positivos (1,18%), desbalanço 83:1. Lacunas documentadas
   (incidentes redundantes, zona cinza = 0, natureza PU).

**Assunção de produção:** o feed de threat-intel é unido como enriquecimento
(reputação de IP/ASN/JA3), não como rótulo.

## 2. Feature engineering (2.2)
Duas famílias (`src/features`):
- **Per-request** (stateless, calculável no edge isolado): path, status/erro,
  body/latência, método, user-agent não-browser, headers (flags/contagens).
- **De fonte — rolling CAUSAL** (janelas 5min + 20 req): taxa, taxa de erro,
  diversidade de endpoints/status, regularidade de timing. Só passado → sem
  leakage e servível em tempo real.
- **Reputação** (threat-intel): booleano `known_bad` separado.

Decisão crítica: **identidade crua (IP/JA3/country) fora** — é quase-lookup do
rótulo e colapsa sob rotação (3.4). O sinal de identidade entra como
*comportamento derivado*, não como o identificador memorizável. As features de
maior poder são as comportamentais de fonte (taxa de erro, diversidade de
endpoints).

## 3. Seleção de modelo (2.3 + 3.2)
**Arquitetura híbrida de duas camadas:**
- **Supervisionado — LightGBM** (raso, 120 árvores): preciso em ataques
  conhecidos; pequeno e rápido para o edge; probabilidades calibráveis.
- **Não-supervisionado — IsolationForest** (treinado só em benigno): rede de
  segurança para ataque **novo** — fecha a cegueira do supervisionado comprovada
  no leave-one-class-out.
- **Decisão = OR** (supervisionado reconhece **ou** anomalia dispara).
- Desbalanço via `class_weight` só no treino; probabilidade **calibrada**
  (Platt/isotonic) para o limiar por custo fazer sentido.
- Regressão Logística fica como referência/alvo de distilação, não em produção.

## 4. Metodologia de treino (2.3 + validação)
- **Split temporal** (treina no passado, testa no futuro) + **walk-forward** para
  variância; nunca embaralhar o tempo.
- **Pré-processamento dentro do Pipeline**, ajustado só no treino (sem leakage).
- **Bateria de validação crítica** (`src/modeling/validate.py`): label-shuffle
  (pipeline limpo), baseline trivial (dado sintético é fácil → métrica honesta via
  walk-forward ~0,92), split por fonte (generaliza por comportamento),
  leave-one-class-out (supervisionado cego a ataque novo → motiva o híbrido).
- **Hiperparâmetros** por busca enxuta orientada a edge: o menor modelo que
  mantém a performance (D15).

## 5. Estratégia de deploy no edge (2.4 + 3.1)
- **Modelo compilado** para código sem dependências (`m2cgen` → JS/WASM); a
  aritmética custa ~2µs/req (2.500× sob os 5ms). Modelo não é o gargalo.
- **Estado de sessão** (3.1): estado **agregado por fonte** (EWMA/ring buffer/HLL)
  num **Durable Object** com roteamento sticky por chave + cache local do PoP +
  write-behind. O caminho quente é dominado por **1 leitura de estado**.
- **Limiar por custo** (3.3): `q* = C_FP/(C_FP+C_FN)` sobre probabilidade
  calibrada — ~0,96 no baseline, ~0,33 em campanha. **Dinâmico** (chaveia por
  regime) e **condicional a endpoint** (checkout é extra-conservador).
- **Degradação graciosa:** se o estado cair, cai para o modelo per-request +
  anomalia/reputação, com fail-open nos fluxos de pagamento.
- **Atualização de modelo** = publicar novo artefato compilado (deploy canário/
  shadow); sem chamada a servidor central no caminho quente.

## 6. Monitoramento em produção (3.2 + 3.4)
- **Drift:** monitorar shift de distribuição das features e **taxa de anomalia**;
  pico sinaliza padrão novo → alerta + possível modo campanha + retreino.
- **Loop de rótulos:** 3 fontes com confiança distinta (WAF triggers instantâneos
  de alta precisão; forense atrasada de alta qualidade; red team). **Active
  learning** prioriza as anomalias não reconhecidas pelo supervisionado; **weak/
  pseudo-labels** permitem retreino antecipado.
- **Cadência de retreino curta** (drift semanal) com validação temporal antes de
  promover.
- **Robustez adversarial:** meta-features de variabilidade (churn de JA3/timing)
  tornam a evasão auto-incriminatória; red-teaming contínuo realimenta o treino;
  ancorar features no **objetivo do ataque** (caro de falsificar).
- **Métricas de negócio:** acompanhar o **custo** (FP/FN em $) e a taxa de bloqueio
  em fluxos de pagamento, não só precision/recall.

## Fecho
O sistema é um **detector híbrido calibrado por custo**, servido compilado no
edge com estado agregado por fonte, avaliado com rigor (validação que separou
sinal de artefato), com limites conhecidos (`api_abuse`/mimicry) e um ciclo de
retreino que fecha o gap de rotulagem. Cada peça foi decidida por evidência
(métricas e testes), documentada em `docs/DECISIONS.md` (D1–D18).
