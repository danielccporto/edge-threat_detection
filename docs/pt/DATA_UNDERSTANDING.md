# Entendimento das Bases de Dados — CloudWalk Edge Security Case

> Documento de referência da fase de exploração. Base: 7 dias de tráfego sintético
> (2025-01-06 → 2025-01-12) que passou pela camada de edge/WAF.

## Visão geral dos arquivos (`data/raw/`)

| Arquivo | Grão (1 linha =) | Linhas | PK |
|---|---|---|---|
| `http_requests.csv` | 1 requisição HTTP | 50.000 | `request_id` |
| `request_headers.csv` | 1 header de 1 requisição | 146.439 | (`request_id`, `header_name`) |
| `incident_labels.csv` | 1 rótulo de incidente (fonte + janela) | 103 | `incident_id` |

---

## 1. `http_requests` — tabela-fato central

Log request-level. É a **espinha dorsal** do projeto: tudo se liga a ela.

| Coluna | Tipo | Papel | Observações |
|---|---|---|---|
| `request_id` | string hex | **PK** | 50.000 únicos, sem nulos |
| `timestamp` | ISO8601 UTC | temporal | janela 2025-01-06T00:01 → 2025-01-12T21:31; usado no split temporal e no join com incident |
| `source_ip` | IPv4 | **FK lógica** p/ incident (ip / ip_range) | 1.353 IPs distintos |
| `method` | enum | feature | GET, POST, PUT, DELETE, HEAD, OPTIONS |
| `path` | string | feature | 3.508 distintos (há query strings/paths variados) |
| `status_code` | int | feature | 10 valores; concentra 200/201, mas há 4xx/5xx e 429 |
| `response_time_ms` | int | feature | latência de origem |
| `body_size_bytes` | int | feature | tamanho do corpo |
| `user_agent` | string | feature | **só 14 distintos** (sintético); inclui browsers e clients `python-requests`, `axios` |
| `tls_fingerprint` | string ja3 | **FK lógica** p/ incident (tls_fingerprint) | **só 9 JA3 distintos** no dataset inteiro |
| `country` | ISO2 | feature | 16 países; 69% BR, 15% US |
| `asn` | string ASxxxx | feature | 268 ASNs |

Sem valores vazios em nenhuma coluna.

## 2. `request_headers` — detalhe (long format) 1:N com requests

Formato chave-valor (EAV). Cada request tem em média **2,93 headers**.

- **FK:** `request_headers.request_id → http_requests.request_id`. Integridade **perfeita**: 0 órfãos, 0 requests sem header.
- **PK composta:** (`request_id`, `header_name`) — 100% única (nenhum header repete dentro da mesma request).
- 9 `header_name` distintos. Frequência: `Accept` (42k), `Accept-Language` (29k), `Accept-Encoding` (21k), `Content-Type` (18k), `Cookie` (12k), `Referer` (10k), `Authorization` (7k), `X-Request-ID` (4k), `User-Agent` (6).
- Sinais ricos para features: presença/ausência de `Cookie`/`Authorization` (sessão autenticada?), `Accept-Language` coerente com `country`, `Content-Type` vs `method`, ausência de `Referer`.
- **Para usar em ML é preciso pivotar** (long → wide: uma coluna por header) ou derivar flags/contagens por `request_id`.

## 3. `incident_labels` — rótulos (verdade-terra atrasada e por fonte)

NÃO rotula requests diretamente — rotula **fontes dentro de janelas de tempo**. Daí a necessidade do join temporal.

| Coluna | Papel |
|---|---|
| `incident_id` | PK (103 únicos) |
| `source_identifier` | o identificador da fonte (42 distintos — fontes se repetem em vários incidentes) |
| `identifier_type` | **como casar**: `ip` (match exato), `ip_range` (CIDR → contém), `tls_fingerprint` (match exato no ja3) |
| `attack_class` | credential_stuffing, api_abuse, ddos_l7, scanner, zero_day_exploit |
| `confidence` | high (64) / medium (28) / low (11) → peso do rótulo |
| `labeled_at` | quando o label foi criado (**atraso**: dias após o ataque) |
| `active_from` / `active_until` | **janela de validade** do rótulo; só vale para requests cujo `timestamp` cai dentro dela |

Distribuição (`identifier_type` × `attack_class`): a maioria é `ip` (89), com 8 `ip_range` e 6 `tls_fingerprint`. ddos_l7 domina em contagem de incidentes.

---

## Modelo de join (como unir)

```
request_headers.request_id  ──N:1──►  http_requests.request_id   (FK direta, exata)

http_requests  ──many:many (condicional)──►  incident_labels
   condição de match (OR entre os 3):
     • identifier_type='ip'              AND source_ip == source_identifier
     • identifier_type='ip_range'        AND source_ip ∈ CIDR(source_identifier)
     • identifier_type='tls_fingerprint' AND tls_fingerprint == source_identifier
   E SEMPRE: active_from <= timestamp <= active_until   (bound temporal)
```

Regra de rótulo: request é **maliciosa** se casar com ≥1 incidente ativo no seu timestamp; senão **benigna** (positive-unlabeled — ver lacunas).

## Resultado da simulação do join (preview da task 2.1)

- **592 maliciosas (1,18%)** vs **49.408 benignas (98,82%)**.
- Por classe (1º match): credential_stuffing 249, ddos_l7 247, api_abuse 65, scanner 25, zero_day 6.
- Matches por tipo: ip 557, ip_range 313, ja3 567 (somam >592 porque uma mesma request casa simultaneamente por ip+range+ja3; 0 conflitos de classe).

## Lacunas e ambiguidades de rotulagem (discussão exigida na 2.1)

1. **Janela fora do período dos logs:** INC-0071 (api_abuse, 13-14/jan) está depois do último log (12/jan) → não rotula nada. Reflete o atraso real dos labels.
2. **Cobertura parcial (recall dos labels):** incident_labels só cobre ataques já forenseados. Benigno = "não rotulado", não "comprovadamente limpo" → problema **Positive-Unlabeled**; FN nos labels viram ruído no treino.
3. **Overlap de identificadores:** um IP pode cair em `ip` e `ip_range` ao mesmo tempo. Precisamos deduplicar por request e decidir a classe (aqui não houve conflito, mas o código deve ser robusto a isso).
4. **Confidence heterogênea:** labels `low`/`medium` são mais ruidosos — candidatos a peso de amostra ou a exclusão em validação.
5. **Granularidade da fonte:** ip_range rotula a faixa inteira — pode varrer IPs legítimos coabitando o CIDR (risco de falso positivo no label).
6. **Prevalência do sample (1,18%) ≠ produção (<0,1%):** ataques foram amplificados no sintético; a calibração de threshold deve assumir a prevalência real de produção, não a do dataset.

---

## Sobre a 4ª fonte ausente (`threat_intel_feed`)

Citada na Parte 1 e **não entregue** como CSV. Os deliverables da Parte 2 pedem explicitamente apenas os 3 arquivos acima → **a implementação é 100% viável sem ela**. O feed entra como **componente de design** (feature de enriquecimento / regra de fast-path) na escrita das Partes 1 e 3, tratado como sinal externo de ~30% de cobertura. Opcionalmente podemos derivar um proxy do feed a partir dos próprios incidentes de alta confiança, deixando claro que é uma simulação.
