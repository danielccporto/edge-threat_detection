# 2.1 — Relatório de Rotulagem (Join Temporal)

- Total de requests: **50,000**
- Maliciosas: **592** (1.184%)
- Benignas: **49,408** (98.816%)
- Razão de desbalanço (benigno:maligno): **83:1**

## Maliciosas por attack_class
- credential_stuffing: 249
- ddos_l7: 247
- api_abuse: 65
- scanner: 25
- zero_day_exploit: 6

## Maliciosas por confidence do rótulo
- high: 521
- medium: 65
- low: 6

## Cobertura por tipo de identificador (requests tocadas por cada match)
- ip: 557
- ip_range: 308
- ja3: 567
- requests com múltiplos incidentes casados: 532

## Fontes maliciosas distintas
- IPs distintos com >=1 request maliciosa: 33
- JA3 distintos com >=1 request maliciosa: 5

## Lacunas e ambiguidades de rotulagem
- Janela dos logs: 2025-01-06 00:01:01+00:00 → 2025-01-12 21:31:45+00:00
- Incidentes com janela fora do período dos logs (não rotulam nada): **1**
    - INC-0071 | api_abuse | 2025-01-13 13:00:00+00:00 → 2025-01-14 01:00:00+00:00
- Incidentes dentro da janela mas sem request casada: **36** — investigados: em 100% dos casos a fonte *existe* nos logs, mas todo o tráfego dela cai FORA da janela estimada do incidente (janelas são estimativas forenses, nem sempre alinhadas ao tráfego observado).
- **Redundância de incidentes:** 24 de 33 IPs têm >1 incidente (máx 19 no mesmo IP). A mesma fonte recebe várias janelas; só as que sobrepõem o tráfego real geram rótulo. => deduplicar por fonte antes de qualquer análise source-level.
- **Zona cinza (fonte conhecida mas request benigna):** 0 — portanto nenhum exemplo positivo é perdido pelos no-match acima; o rótulo em nível de request está completo para as fontes nomeadas.

- **Positive-Unlabeled:** 'benigno' = não-rotulado, não comprovadamente limpo. Falsos-negativos nos rótulos viram ruído no treino.
- **Prevalência da amostra ≠ produção:** aqui ~1,2%; produção <0,1% (ataques amplificados no sintético). Calibrar threshold para prevalência real.
- **ip_range** rotula a faixa inteira: risco de varrer IPs legítimos coabitando o CIDR (ruído de rótulo).