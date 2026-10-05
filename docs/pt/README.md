# CloudWalk — Detecção de Tráfego Malicioso no Edge

Sistema de ML para classificar requisições HTTP como maliciosas/benignas em tempo
real no **edge** (CDN/WAF), sob <5ms/req, sem GPU e com runtime restrito (WASM).
Resposta ao *ML Engineer – Edge Security Assessment*.

**Modelo final:** híbrido de duas camadas — **LightGBM** (ataques conhecidos) +
**IsolationForest** (anomalia, cobre ataques inéditos), com decisão por OR e
limiar calibrado por **custo**.

---

## Estrutura do projeto

```
ca_case/
├── data/
│   ├── raw/           # CSVs originais (imutáveis)
│   └── interim/       # derivados tipados em Parquet (gerados; gitignored)
├── src/
│   ├── ingestion/     # padronização + contrato de schema  (standardize, schema)
│   ├── labeling/      # join temporal dos rótulos (2.1)      (join_labels, report)
│   ├── features/      # feature engineering (2.2)            (build_features)
│   ├── modeling/      # split, preprocess, tune, train, evaluate, validate, hybrid (2.3)
│   └── deploy/        # benchmark + export p/ edge (2.4)     (benchmark, export_edge)
├── models/            # modelos treinados + models/edge/edge_model.js (gerados)
├── reports/           # saídas e writeups por tarefa (1_design, 2_x, 3_x, ...)
├── docs/              # entendimento, decisões (ADR) e resumos
├── requirements.txt
└── README.md
```

## Setup

Requer **Python 3.11+**.

```bash
python -m venv venv
# Windows:  venv\Scripts\activate     |  Linux/Mac:  source venv/bin/activate
pip install -r requirements.txt
```

## Como rodar (pipeline, em ordem)

Cada etapa lê a saída da anterior. Rode da raiz do projeto:

```bash
# 1. Padronização: data/raw/*.csv -> data/interim/*.parquet (valida o schema)
python -m src.ingestion.standardize

# 2. Rotulagem (2.1): join temporal + relatório de contagens/lacunas
python -m src.labeling.join_labels
python -m src.labeling.report

# 3. Feature engineering (2.2): 35 features -> data/interim/features.parquet
python -m src.features.build_features

# 4. Modelagem (2.3)
python -m src.modeling.tune       # (opcional) busca enxuta de hiperparâmetros
python -m src.modeling.train      # treina LightGBM + LogReg (c/ e s/ country)
python -m src.modeling.validate   # bateria de validação crítica (T1–T4)
python -m src.modeling.hybrid     # modelo híbrido + prova leave-one-class-out

# 5. Edge (2.4)
python -m src.deploy.benchmark    # latência / throughput / tamanho
python -m src.deploy.export_edge  # compila o modelo p/ JS puro (models/edge/)
```

> `data/interim/`, `models/` e `venv/` são gerados e ficam fora do git. Os CSVs
> originais ficam em `data/raw/`.

## Onde está o raciocínio (writeups)

| Documento | Conteúdo |
|---|---|
| [reports/1_design.md](reports/1_design.md) | **Parte 1** — design ponta a ponta (dados→features→modelo→deploy→monitoramento) |
| [reports/2_1_labeling_report.md](reports/2_1_labeling_report.md) | 2.1 — rotulagem, contagens, lacunas |
| [docs/FEATURES.md](docs/FEATURES.md) | 2.2 — catálogo de features + poder preditivo |
| [reports/2_3_model_report.md](reports/2_3_model_report.md) | 2.3 — métricas do baseline |
| [reports/2_3_validation.md](reports/2_3_validation.md) | 2.3 — validação crítica (por que confiar/desconfiar) |
| [reports/2_3_hybrid.md](reports/2_3_hybrid.md) | 2.3 — modelo híbrido e prova em ataque inédito |
| [reports/2_3_tuning.md](reports/2_3_tuning.md) | 2.3 — tuning orientado a edge |
| [reports/2_4_edge.md](reports/2_4_edge.md) | 2.4 — viabilidade no edge (latência/memória/export) |
| [reports/3_1_stateful_edge.md](reports/3_1_stateful_edge.md) | 3.1 — estado num edge stateless |
| [reports/3_2_labeling_bottleneck.md](reports/3_2_labeling_bottleneck.md) | 3.2 — gap de rotulagem (superv ↔ não-superv) |
| [reports/3_3_threshold_economics.md](reports/3_3_threshold_economics.md) | 3.3 — ponto de corte por custo (com as contas) |
| [reports/3_4_adversarial.md](reports/3_4_adversarial.md) | 3.4 — robustez adversarial |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Log de decisões (D1–D18) com contexto e porquê |
| [docs/PROJECT_SUMMARY.md](docs/PROJECT_SUMMARY.md) | Resumo narrado do projeto inteiro |
| [docs/METRICS_EXPLAINED.md](docs/METRICS_EXPLAINED.md) | Métricas explicadas em linguagem simples |
| [docs/DATA_UNDERSTANDING.md](docs/DATA_UNDERSTANDING.md) | Dicionário de dados + modelo de join |

## Resultados-chave (honestos)

- Rotulagem: 592 maliciosas (1,18%), desbalanço 83:1.
- Baseline (teste single-split) parece quase perfeito, **mas** é artefato de dado
  sintético trivial (uma regra de 1 linha quase empata). **Métrica honesta
  (walk-forward): PR-AUC ~0,92.**
- Supervisionado sozinho é **cego a ataque novo** (recall≈0 em classe não vista);
  o **híbrido recupera 4/5 classes** (0,67–0,98). Exceção: `api_abuse` (mimicry).
- Edge: inferência ~2µs/req (2.500× sob os 5ms), modelo ~259KB em JS puro.
- Ponto de corte por custo: ~96% de certeza no baseline, ~33% em campanha ativa.

## Premissas principais
Unidade de decisão = requisição (com contexto de fonte); "benigno" = não-rotulado
(Positive-Unlabeled); prevalência real <0,1% (amostra amplificada); identidade
crua (IP/JA3/country) **excluída** do modelo por vazamento/robustez; threat-intel
feed tratado como feature de reputação (não foi fornecido como dado). Detalhes em
[reports/1_design.md](reports/1_design.md) e [docs/DECISIONS.md](docs/DECISIONS.md).
