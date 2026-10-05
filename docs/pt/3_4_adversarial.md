# 3.4 — Robustez Adversarial

**Cenário:** o atacante descobre que o modelo pesa muito **JA3** e **regularidade
de timing**, passa a **randomizar o JA3 por requisição** e **adicionar jitter**
aos intervalos. A recall cai de 92% para 41%. Plano de resposta?

## Ponto de partida: já estamos parcialmente blindados
Esse ataque mira um modelo que *depende* de JA3 e timing — mas o nosso, **por
decisão de projeto, não depende**:
- **JA3 cru foi EXCLUÍDO** como feature (D12): provamos que era quase-lookup do
  rótulo e que colapsaria sob rotação. Randomizar o fingerprint **não derruba** um
  modelo que nunca o usou.
- **Timing tem peso baixo:** `src_cv_interarrival20` teve poder preditivo de só
  0,56 (quase aleatório) na 2.2. Adicionar jitter degrada pouco um modelo que não
  se apoia nele.

Ou seja, as duas decisões que tomamos lá atrás (não memorizar identidade;
diversificar features) **são a defesa estrutural** contra este exato ataque. Um
modelo ingênuo cairia para 41%; o nosso cai muito menos.

## Mitigação imediata (horas)
1. **Detectar o shift:** monitor de recall + shift de distribuição de features +
   pico de anomalia disparam o alerta (mesmo pipeline da 3.2).
2. **Virar o disfarce em sinal:** randomizar o JA3 *é*, por si só, anômalo. Uma
   fonte que exibe **muitos JA3 distintos numa janela** não é normal → adicionar
   **`ja3_churn` por fonte** (contagem de fingerprints distintos) torna a evasão
   **auto-incriminatória**. O mesmo para jitter artificial (variância alta demais).
3. **Modo campanha (D18):** derrubar o limiar de custo temporariamente → recupera
   recall aceitando mais FP enquanto durar o ataque.
4. **Rede de segurança não-supervisionada:** a camada de anomalia (que não usa
   JA3) continua pegando o desvio comportamental.
5. **Fora-do-ML:** rate-limit e **challenge** (JS/PoW) para fontes suspeitas;
   reputação de IP/ASN via threat-intel segue valendo.

## Mudanças de arquitetura (longo prazo)
1. **Princípio: ancorar no OBJETIVO do ataque, não no disfarce.** O atacante pode
   randomizar JA3 e timing, mas **não pode deixar de fazer o que veio fazer** —
   bater no `/auth/login`, gerar erros de credencial, varrer endpoints. Features
   ligadas ao *goal* (taxa de erro, foco em endpoint sensível, semântica de
   credential stuffing) são **caras de falsificar** sem abortar o ataque.
2. **Defesa em profundidade / diversidade de features:** nenhuma feature isolada
   pode dominar. Já seguimos isso; reforçar com regularização e, se preciso,
   limites de importância por feature.
3. **Treino adversarial:** injetar no treino exemplos com JA3 randomizado e timing
   com jitter, para o modelo **aprender a não depender** desses sinais.
4. **Meta-features de variabilidade:** churn de JA3, entropia de timing,
   diversidade de UA por fonte — a própria *tentativa de se esconder* vira feature.
5. **Red-teaming contínuo:** o time que simula ataques (citado no enunciado)
   realimenta o conjunto de treino com as evasões mais recentes → ciclo fecha com
   a 3.2.

## Veredito
O ataque descrito explora **dependência de features forjáveis** — e nós já a
evitamos por design (JA3 fora, timing com peso baixo), então partimos de uma
posição defensável. A resposta completa é: **transformar a evasão em sinal**
(churn de JA3/timing vira feature), **recorrer à camada não-supervisionada** e ao
**modo campanha** no curto prazo, e no longo prazo **ancorar o modelo no objetivo
do ataque** (o que é caro de falsificar) com **treino adversarial** e
**red-teaming contínuo**. Robustez aqui é consequência das decisões de feature,
não um remendo posterior.
