# 3.2 — The Labeling Bottleneck

**Problema:** os melhores rótulos chegam 1–3 dias depois do ataque; padrões novos
surgem a qualquer momento. Como cobrir o intervalo entre um ataque novo começar e
termos dados rotulados dele?

## A prova que já temos
Nossa validação quantificou exatamente esse gap: no leave-one-class-out (T4), o
supervisionado sozinho teve recall ≈0 em classe nunca vista; o **híbrido com
IsolationForest recuperou 4 de 5** (0,67–0,98). Ou seja, não é teoria — já
construímos e medimos a resposta. A 3.2 formaliza *quando cada modelo manda*.

## A ideia central: quem é o "primeiro a responder"

```
tempo →   ataque novo começa        rótulo chega (1–3 dias)        retreino
          │                          │                              │
NÃO-SUPERV.│■■■■■ cobre o desconhecido ■■■■■                         │ (recua p/ o próximo novo)
SUPERV.    │ (cego a este padrão)          ■■■■ assume este padrão ■■■■■■■■■■■■→
```

- **Não-supervisionado (IsolationForest) = primeiro a responder.** Não precisa de
  rótulo; dispara no desvio do normal. Cobre a **janela cega** (dia 0 até o rótulo
  chegar). Recall alto, mais ruidoso.
- **Supervisionado (LightGBM) = especialista.** Preciso no que já foi rotulado.
  **Assume o padrão** assim que ele entra no conjunto de treino.
- **Handoff:** com o tempo, cada padrão **migra de "pego por anomalia" para "pego
  por supervisão"**. A anomalia fica livre para cobrir o *próximo* desconhecido.

## Estratégia concreta (o loop de rótulos)

**1. Fontes de rótulo, com confiança diferente** (as 3 do enunciado):
- **WAF triggers:** alta precisão, baixa recall, **instantâneos** → usáveis já,
  como rótulos fracos positivos.
- **Forense pós-incidente:** alta qualidade, **atrasado 1–3 dias** → o gabarito.
- **Red team:** limpo e controlado → ótimo para classes raras.

**2. Fechar o gap mais rápido (active learning):** as anomalias que a camada
não-supervisionada dispara **e que o supervisionado não reconhece** são a fila de
maior valor para **revisão/rotulagem prioritária**. Em vez de esperar passivo os
1–3 dias, direcionamos o esforço humano para os casos que mais importam.

**3. Rótulos provisórios (weak/pseudo-labeling):** anomalias de altíssimo score +
WAF triggers viram **rótulos positivos provisórios** (peso menor) para **retreinar
antes** da confirmação forense — encurtando o gap de dias para horas, com o
cuidado de baixar o peso para não envenenar o modelo.

**4. Cadência de retreino curta:** como o drift é semanal, retreino **frequente**
(diário/semanal) com deploy canário/shadow (lembrando que publicar modelo no edge
= publicar novo artefato, D16). Assim o supervisionado absorve rápido o que a
anomalia e os rótulos novos trouxeram.

**5. Monitorar o gatilho:** pico na **taxa de anomalia** ou shift de distribuição
de features sinaliza padrão novo em curso → alerta + possível **modo campanha**
(que também derruba o limiar de custo, D18) + retreino antecipado.

## Quando cada um "manda" (resumo explícito)
| Momento | Primário | Papel do outro |
|---|---|---|
| Ataque novo, sem rótulo | **Não-supervisionado** | supervisionado cobre os conhecidos |
| Rótulo fraco (WAF/anomalia) chega | ambos; retreino provisório | começa o handoff |
| Rótulo forense confirmado + retreino | **Supervisionado** | anomalia volta a vigiar o próximo novo |
| Regime estável | Supervisionado (precisão) | anomalia = rede de segurança (recall) |

## Limite honesto
O `api_abuse` (mimicry low-and-slow) é o pior caso deste gap: não é anômalo
(parece legítimo) **e** a forense demora a enxergá-lo → nem a rede de segurança
nem o rótulo chegam rápido. Mitigação: **features de sessão de horizonte mais
longo** e detecção por comportamento agregado — trabalho futuro, o mesmo vetor da
3.4.

## Veredito
O gap de rotulagem se resolve com **divisão de trabalho no tempo**: a anomalia
não-supervisionada é a **rede de segurança imediata** para o desconhecido; o
supervisionado **assume cada padrão** assim que o rótulo (fraco→confirmado) chega,
acelerado por active learning e retreino frequente. É a mesma arquitetura híbrida
que já medimos — aqui vista pela ótica do *tempo* e do *fluxo de rótulos*.
