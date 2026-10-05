# 3.1 — Edge Stateless, Sinais Stateful

**Problema:** as features mais fortes (`src_rate_5min`, `src_err_rate20`, …)
exigem lembrar o histórico recente de cada fonte. Mas o edge é stateless: cada
requisição pode cair num PoP diferente, sem memória compartilhada. Como manter o
contexto de sessão sem estourar os 5ms?

## Princípio: guardar *estado agregado*, não eventos

Não armazenamos a lista de requisições da fonte (cresce sem limite e encarece a
leitura). Guardamos um **resumo de tamanho fixo por fonte** (~centenas de bytes),
atualizável em O(1):
- **Contadores com decaimento temporal (EWMA)** para taxa e taxa de erro — em vez
  de recontar uma janela, aplicamos decaimento exponencial a cada evento.
- **Ring buffer das últimas 20** (ou timestamps recentes) para as features de
  contagem.
- **Sketch de cardinalidade** (HyperLogLog pequeno) para diversidade de endpoints.

Isso mantém o estado minúsculo e a atualização barata — essencial para caber no
orçamento.

## Arquitetura concreta (padrão Cloudflare)

```
Requisição
  │
  ├─ roteia por CHAVE DE FONTE (hash do IP/JA3) → sempre o MESMO Durable Object
  │
  ▼
Worker (PoP)
  1. lê cache local em memória do PoP (best-effort)        ~µs
  2. se miss, lê o Durable Object da fonte (co-localizado)  ~1–a poucos ms
  3. calcula features per-request (inline) + features do estado
  4. scoreRequest(features) + anomalia                      ~µs
  5. decisão (OR + limiar)                                  → allow/throttle/block
  6. atualiza o estado em WRITE-BEHIND (fora do caminho quente)
```

Três escolhas que resolvem o "cada request num nó diferente":
- **Roteamento por chave (sticky by source):** o hash da fonte leva sempre ao
  mesmo **Durable Object** (DO) — um objeto por fonte, com atualização serializada
  e consistente. Assim o "nó diferente" deixa de ser problema: o estado da fonte
  tem um dono único e co-localizado.
- **Cache local do PoP** como primeira camada (leitura em µs); o DO é a fonte de
  verdade quando dá miss.
- **Write-behind:** a atualização do estado acontece **depois** de responder, não
  bloqueia a decisão.

## Implicações de latência

- Leitura local (cache do PoP): ~µs. Leitura do DO co-localizado: ~1 a poucos ms.
  **Esse é o maior termo do orçamento** — o modelo (~2µs) é desprezível perto
  disso.
- Para caber nos 5ms: (a) **co-localizar** estado e computação (DO na mesma
  região), (b) **sticky routing** por fonte para maximizar acerto de cache e
  evitar saltos entre regiões, (c) **write-behind** para tirar a escrita do
  caminho quente, (d) ler só o necessário (o resumo agregado, não eventos).
- Resultado: o caminho quente fica dominado por **uma leitura de estado**; tudo
  o mais é µs.

## O que quebra se o state store cair (degradação graciosa)

Se o DO/KV ficar indisponível, perdemos as features `src_*` — justamente as mais
preditivas. O sistema **não pode simplesmente falhar**; degrada em camadas:

1. **Modo degradado (per-request only):** como separamos features per-request de
   features de fonte, há um **modelo de fallback** que usa só sinais locais
   (status/erro, UA não-browser, headers, path). Perde recall, mas continua
   funcional sem estado.
2. **Camada de anomalia local + reputação:** o IsolationScore sobre features
   per-request e o booleano de threat-intel (reputação) seguem valendo sem estado
   compartilhado.
3. **Contadores locais do PoP:** mesmo sem o store central, cada PoP mantém uma
   visão aproximada em memória — pior que a global, melhor que nada.
4. **Política fail-open vs fail-closed:** como **FP é caro** (bloquear pagamento),
   em outage de estado inclinamos para **fail-open na decisão de bloqueio de
   fluxos sensíveis** (não bloquear com sinal degradado), mantendo **rate-limiting
   grosseiro local** como rede de proteção. É uma decisão de negócio, explicitada.

**Ponto fraco conhecido:** com estado só local por PoP, uma fonte que rotaciona
entre PoPs escapa dos contadores locais — mitigado pelo sticky routing por chave
ao DO (estado com dono único).

## Conexão com o resto
Isto fecha a ressalva da 2.4: o modelo não é o gargalo de latência/throughput; a
**leitura de estado é**. O design acima mantém o caminho quente em ~1 leitura +
µs de cômputo, e degrada com segurança (viés a não bloquear cliente legítimo)
quando o estado falha.
