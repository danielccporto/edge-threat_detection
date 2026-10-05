# Entendendo o Projeto do Zero — CloudWalk Edge Security

> Um passeio explicado por tudo o que fizemos, para quem está chegando agora.

## O que estamos tentando resolver

A CloudWalk processa bilhões de requisições HTTP por dia no edge da sua
infraestrutura (a camada de CDN/WAF, que fica entre a internet e os servidores
da empresa). Parte desse tráfego são ataques — gente tentando adivinhar senhas,
abusar de APIs, derrubar serviços. Hoje isso é barrado por regras fixas escritas
à mão, que erram muito: bloqueiam cliente legítimo em pico de venda e deixam
passar atacante esperto.

A missão: construir um **modelo de machine learning que decida, em tempo real,
se cada requisição é maliciosa ou não** — rápido o suficiente para rodar na
próprio edge (menos de 5 milissegundos por requisição, sem GPU, em um ambiente
muito restrito). E com um detalhe caro: **bloquear um cliente legítimo num
pagamento custa dinheiro**, então errar para o lado de bloquear é perigoso.

O problema tem quatro dificuldades de fundo que guiaram todas as decisões:
1. **Ataques são raríssimos** (menos de 0,1% do tráfego) — a "agulha no palheiro".
2. **Os rótulos chegam atrasados e incompletos** — a equipe de segurança só
   confirma que algo foi ataque dias depois, e nem todo ataque é descoberto.
3. **Atacantes mudam de tática toda semana** — o que funcionava ontem falha hoje.
4. **Um clique isolado parece inocente** — o ataque só aparece quando você olha a
   *sequência* de requisições de uma mesma origem.

## Os dados que recebemos

Três tabelas (planilhas), 7 dias de tráfego simulado:
- **`http_requests`** — o registro de cada requisição (50 mil linhas): quem
  mandou (IP), quando, para qual endereço, que resposta recebeu, etc. É a tabela
  central.
- **`request_headers`** — os "cabeçalhos" de cada requisição (146 mil linhas):
  detalhes técnicos como se a requisição trazia um cookie de sessão, um token de
  autenticação, etc.
- **`incident_labels`** — a lista de incidentes confirmados pela segurança (103
  linhas): "o IP X esteve atacando entre tal e tal horário". É o nosso gabarito.

## Passo 1 — Arrumar a casa (padronização)

Dados brutos vêm sujos: tudo chega como texto, nomes de colunas inconsistentes,
datas em formatos diferentes. Antes de qualquer análise, criamos uma etapa que
**converte cada campo para o tipo certo** (data vira data, número vira número) e
**confere a integridade** (não há IDs duplicados? não faltam campos essenciais?).
Guardamos o resultado limpo em um formato eficiente (Parquet) que **preserva
esses tipos**. É o alicerce: sem isso, bugs silenciosos apareceriam lá na frente.

## Passo 2 — Criar o gabarito (rotulagem)

Aqui mora a primeira sutileza. A lista de incidentes não diz "a requisição 123
foi maliciosa"; ela diz "o IP X era malicioso entre 3h e 6h". Então tivemos que
**cruzar** as duas coisas: uma requisição é maliciosa **se** veio de uma origem
fichada **e** aconteceu dentro da janela de tempo daquele incidente. Respeitar a
janela é crucial — a mesma origem pode ser atacante de madrugada e estar quieta
de tarde.

Resultado: **592 requisições maliciosas (1,18%)** contra 49.408 benignas — ou
seja, **83 benignas para cada maliciosa**. Esse desequilíbrio enorme é o cenário
real e moldou todas as escolhas seguintes. Também descobrimos, investigando, que
muitos incidentes eram "repetidos" (a mesma origem fichada várias vezes) e que
"benigno" aqui significa na verdade "não foi fichado" — não necessariamente
"comprovadamente limpo".

## Passo 3 — Transformar registros em sinais (feature engineering)

Um modelo não entende "requisição"; ele entende números. Então transformamos
cada requisição em **35 sinais mensuráveis**, em duas famílias:
- **Sinais da própria requisição:** o endereço acessado é sensível (tela de
  login)? a resposta foi um erro? o corpo é minúsculo? o programa que enviou
  parece um navegador de verdade ou um script automatizado?
- **Sinais do comportamento da origem ao longo do tempo:** quantas requisições
  aquele IP fez nos últimos 5 minutos? qual a fração de erros? ele fica martelando
  um único endereço (típico de ataque) ou navega por vários (típico de humano)?

Esses sinais de comportamento são calculados **olhando só para o passado** de
cada origem (nunca o futuro), porque é assim que o edge funciona na vida real.
Quando medimos quais sinais mais separam ataque de tráfego normal, os campeões
foram justamente os **comportamentais** — confirmando a intuição: o ataque se
revela na sequência, não no clique isolado.

## Passo 4 — Escolher e treinar os modelos

Testamos dois tipos, de propósito em pontas opostas:
- **LightGBM** (uma floresta de árvores de decisão "turbinada") — preciso e ainda
  assim pequeno/rápido, nosso modelo principal.
- **Regressão Logística** (um modelo linear simples) — o mais leve possível, para
  mostrar o piso que caberia com folga no edge.

Três cuidados importantes de método:
- **Desequilíbrio:** em vez de inventar dados falsos de ataque, dissemos ao
  modelo para "dar mais peso" aos raros exemplos maliciosos.
- **Separação por tempo (não aleatória):** treinamos nos 5 primeiros dias e
  testamos nos 2 últimos. Como na realidade sempre prevemos o futuro com o
  passado, embaralhar os dias seria trapaça (o modelo "veria o futuro").
- **Não demos ao modelo a "identidade" crua** (o IP ou a impressão digital TLS).
  Mostramos com dados que esses campos eram praticamente a resposta copiada do
  gabarito — o modelo decoraria os atacantes conhecidos e seria inútil contra
  qualquer atacante novo (que é justamente o que acontece na prática).

## Passo 5 — Desconfiar dos resultados (a parte mais importante)

O modelo deu métricas quase perfeitas. **Isso nos deixou desconfiados, não
felizes** — resultado perfeito quase sempre esconde um problema. Então fizemos
quatro testes para interrogar nosso próprio trabalho:
1. **Embaralhamos os rótulos** de propósito: o modelo passou a errar tudo (bom —
   significa que **não há bug/vazamento** no código).
2. **Comparamos com uma regra boba de uma linha:** ela quase empatou com o
   modelo. Ou seja, **os ataques simulados são fáceis demais** de separar; a nota
   alta reflete o dado, não a genialidade do modelo.
3. **Testamos com origens nunca vistas:** o modelo se saiu razoavelmente bem,
   provando que ele aprendeu *comportamento*, não decorou identidades.
4. **Escondemos um tipo de ataque inteiro do treino:** o modelo **não conseguiu
   detectá-lo**. Esse foi o achado decisivo: um modelo que só reconhece o que já
   viu **falha exatamente no cenário que motiva o projeto** (ataques novos a cada
   semana).

## Passo 6 — Consertar a lacuna (modelo híbrido)

Como resolver "não detecta ataque novo"? Adicionando um segundo modelo com uma
lógica oposta: o **IsolationForest**. Enquanto o primeiro aprende a reconhecer
ataques conhecidos, este aprende apenas **como é o tráfego normal** e dispara um
alerta para qualquer coisa fora do padrão — mesmo um ataque que nunca viu.

A decisão final passou a ser: **bloqueia se o modelo principal reconhece um
ataque conhecido OU se o detector de anomalia acha que está muito estranho.**

Testamos de novo escondendo cada tipo de ataque: o híbrido **recuperou a detecção
em 4 dos 5 tipos** (de recall ~0 para 0,67–0,98). A exceção, que relatamos com
honestidade, é um ataque que **imita o tráfego legítimo** (devagar, sem erros) —
o mais difícil de todos, e um ponto para evolução futura.

## Passo 7 — Provar que roda no edge (viabilidade de deploy)

O edge é um ambiente apertado (menos de 5ms por requisição, sem GPU). Medimos e
o resultado foi tranquilizador: **o modelo é a parte barata**. A conta real da
decisão leva **~2 microssegundos** por requisição (2.500× abaixo do limite) e o
modelo ocupa só algumas centenas de KB. Confirmamos exportando o modelo final
para **JavaScript puro, sem nenhuma dependência** (um arquivo pronto para rodar
num Cloudflare Worker). A lição: o verdadeiro desafio de tempo não é o modelo, e
sim **lembrar o histórico recente de cada origem** (o "estado") num ambiente que,
por natureza, não guarda memória — assunto da próxima parte.

> Nota: a Regressão Logística citada antes era só um **ponto de comparação**. O
> modelo que vai para produção é o **híbrido (LightGBM + IsolationForest)**.

## Passo 8 — Responder às perguntas difíceis de produção (Parte 3)

Com o sistema pronto, enfrentamos os quatro dilemas práticos do enunciado:

- **Como guardar "memória" num ambiente sem memória? (3.1)** Em vez de guardar
  todo o histórico de cada origem, guardamos um **resumo pequeno** (taxa, erros,
  variedade de acessos) numa peça de estado que "pertence" àquela origem, com uma
  cópia local para ler rápido e a escrita feita *depois* de responder. O que custa
  tempo é consultar essa memória (~milissegundos), não o modelo. E se essa memória
  cair, o sistema **degrada com segurança**: volta a usar só os sinais da
  requisição isolada e, em telas de pagamento, prefere **não bloquear** (porque
  bloquear cliente é caro).

- **Quando bloquear, em dinheiro? (3.3)** Mostramos que o ponto de corte **não é
  um número fixo, é uma conta de custo**: como bloquear um cliente ($2,50) é 25×
  mais caro que deixar um ataque passar ($0,10), só se deve bloquear com **~96% de
  certeza**. Mas, durante um ataque intenso (custo sobe para $5,00), a conta vira
  e passa a valer bloquear já com **~33% de certeza**. Ou seja: o rigor do porteiro
  **muda sozinho conforme o risco do momento**.

- **E enquanto o ataque é novo e ainda não tem "ficha"? (3.2)** O detector de
  anomalia é o **primeiro a responder** (cobre o desconhecido); quando a ficha do
  ataque finalmente chega (1–3 dias depois), o modelo principal **assume** aquele
  padrão. Aceleramos esse ciclo priorizando a investigação dos casos mais
  suspeitos e retreinando com frequência.

- **E se o atacante tentar enganar o modelo? (3.4)** O ataque clássico é mudar a
  "impressão digital" e o ritmo das requisições. Aqui tivemos sorte de ter sido
  cuidadosos antes: **nosso modelo já não depende desses campos** (nós os
  excluímos de propósito), então o truque funciona mal contra ele. Além disso, a
  própria tentativa de disfarce **vira pista** (trocar de impressão digital a cada
  requisição é, em si, anormal), e no longo prazo ancoramos o modelo no que o
  atacante **não pode deixar de fazer** para atingir o objetivo dele.

## Onde estamos e o que falta

Temos um **sistema de detecção em duas camadas** (conhecido + anômalo), avaliado
com rigor, com os limites mapeados, **comprovadamente implantável no edge** e com
as **quatro perguntas de produção respondidas** (Parte 3). Falta apenas
**empacotar**:
- o **texto de design ponta a ponta** (Parte 1), que costura dados → features →
  modelo → deploy → monitoramento numa narrativa única;
- o **README** com o passo a passo de como rodar o projeto.

## Resumo dos números

| O que medimos | Resultado | Como ler |
|---|---|---|
| Nota "de vitrine" no teste | quase perfeita | enganosa (dado fácil) |
| Nota honesta (validação temporal) | ~0,85–0,92 | o número realista |
| Detecção de ataque **conhecido** | alta | forte |
| Detecção de ataque **novo** (só principal) | ~0 | limite do supervisionado |
| Detecção de ataque **novo** (híbrido) | 0,67–0,98 | lacuna resolvida |
| Custo da decisão por requisição | ~2µs | 2.500× abaixo do limite de 5ms |
| Tamanho do modelo exportado | ~259 KB (JS puro) | cabe folgado no edge |
| Ponto de corte ótimo (baseline) | ~96% de certeza | bloquear é 25× mais caro que deixar passar |
| Ponto de corte (ataque intenso) | ~33% de certeza | o rigor se ajusta ao risco do momento |
