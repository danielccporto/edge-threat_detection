# 3.3 — Threshold Economics (calibração do ponto de corte por custo)

## Premissas (enunciado)
- Bloquear uma requisição legítima (pagamento): **C_FP = $2,50**.
- Um ataque que chega ao origin: **C_FN = $0,10**.
- Volume: **100M req/dia**; prevalência real **0,05%** → 50.000 ataques/dia,
  99.950.000 benignas/dia.

## O modelo de custo
Decisão por requisição: **bloquear** ou **deixar passar**. Só dois erros custam:
```
Custo(t) = FP(t) · C_FP  +  FN(t) · C_FN
```
(FP = benignas bloqueadas; FN = ataques que passaram.) Bloquear corretamente um
ataque e deixar passar uma benigna custam ~0.

## Ponto de corte ótimo (decisão bayesiana)
Para uma requisição com probabilidade `q = P(maliciosa)`, comparamos o custo
esperado das duas ações:
- **Bloquear:** se for benigna (prob. `1−q`) pago C_FP → esperado `(1−q)·C_FP`.
- **Passar:** se for ataque (prob. `q`) pago C_FN → esperado `q·C_FN`.

Bloqueio compensa quando `(1−q)·C_FP < q·C_FN`, que resolve para:
```
q* = C_FP / (C_FP + C_FN)        (limiar na probabilidade calibrada)
```

### Baseline
```
q* = 2,50 / (2,50 + 0,10) = 2,50 / 2,60 = 0,962
```
**Só bloqueie quando estiver ~96% certo de que é ataque.** Equivalente em
precisão: o conjunto bloqueado precisa ter **precisão ≥ 0,962** para ser
lucrativo (mesma conta vista pelo lado da precisão):
```
bloquear vale a pena se  P·C_FN > (1−P)·C_FP  →  P > C_FP/(C_FP+C_FN) = 0,962
```

## Por que tão conservador? (as âncoras de custo diário)
- **Não bloquear nada:** 50.000 ataques × $0,10 = **$5.000/dia**. É o teto de
  prejuízo dos ataques — baixo, porque ataque é barato e raro.
- **Bloquear tudo:** 99,95M × $2,50 = **~$250 milhões/dia**. Catastrófico.
- Como C_FP é **25× C_FN**, o risco de errar bloqueando domina. A economia máxima
  que o ML pode trazer no baseline é só os $5.000/dia — então, em período calmo,
  **o principal trabalho do modelo é NÃO gerar falso positivo**, não "pegar mais".

Exemplo: operando em precisão 0,99 e recall 0,90, economia líquida ≈
`5.000·0,90·(1 − 25·0,01/0,99)` ≈ **$3,4k/dia** (de um teto de $5k). Em precisão
0,962 (breakeven) a economia líquida ≈ 0.

## Regime de campanha ativa (C_FN = $5,00)
Durante um credential stuffing ativo, o custo de deixar passar sobe para $5,00:
```
q* = 2,50 / (2,50 + 5,00) = 2,50 / 7,50 = 0,333
```
**Agora bloqueie já com ~33% de certeza** (precisão ≥ 0,333). O limiar **despenca**
porque cada ataque perdido agora dói 50× mais que antes em termos relativos. E a
economia máxima vira 50.000 × $5,00 = **$250k/dia** — é aqui que o sistema
"paga o próprio salário", justificando aceitar muito mais falso positivo.

| Regime | C_FN | Limiar q* | Precisão mínima | Postura | Economia máx./dia |
|---|---|---|---|---|---|
| Baseline | $0,10 | **0,962** | 0,962 | muito conservador | $5k |
| Campanha | $5,00 | **0,333** | 0,333 | agressivo | $250k |

## Implicações de engenharia
1. **Precisa de probabilidade calibrada** (Platt/isotonic sobre o LightGBM), senão
   `q` não tem significado e o limiar vira chute.
2. **Limiar dinâmico por regime:** detectar campanha (pico de volume/anomalia)
   e **chavear C_FN** → o limiar cai automaticamente de 0,962 para ~0,33.
3. **Limiar por endpoint:** C_FP só é $2,50 em fluxo de pagamento. Em endpoints
   sem receita o C_FP efetivo é menor → pode-se bloquear mais agressivamente lá e
   ser extra-conservador no checkout. O limiar deveria ser **condicional ao
   endpoint**, não global.
4. **Casa com a 3.1 (T3):** vimos que o limiar não transfere entre populações →
   calibração por população + por regime é parte do deploy, não um número fixo.

## Veredito
O ponto de corte **não é um número, é uma função do custo**: `q* =
C_FP/(C_FP+C_FN)`. No baseline, bloquear só com ~96% de certeza (FP é 25× mais
caro que FN, e o upside do ML é pequeno — o foco é não criar FP). Em campanha
ativa, o limiar cai para ~33% e o upside explode para $250k/dia. A solução
correta é um **limiar dinâmico, calibrado, condicional a regime e a endpoint** —
não um 0,5 fixo.
