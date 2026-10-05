# As Métricas Explicadas em Linguagem Simples

> Imagine nosso modelo como um **porteiro** numa portaria. A cada pessoa que
> chega (cada requisição), ele decide: **deixo entrar** (benigno) ou **barro**
> (ataque). Todas as métricas abaixo medem o quão bom é esse porteiro.
>
> Em cada ponto, a linha **`No projeto →`** conecta a explicação ao modelo, à
> técnica e ao arquivo onde a decisão foi tomada/encontrada.

## Os três "porteiros" que usamos (ficha técnica)

| Apelido | Modelo real | Como aprende | Papel |
|---|---|---|---|
| Porteiro esperto | **LightGBM** (floresta de árvores turbinada) | com gabarito (supervisionado) | titular — ataques conhecidos |
| Porteiro simples | **Regressão Logística** | com gabarito (supervisionado) | piso leve p/ ambiente apertado |
| Porteiro do "estranho" | **IsolationForest** | só com tráfego normal (não-supervisionado) | fareja o inédito |

Onde cada etapa vive: `src/modeling/` (`split.py`, `preprocess.py`, `tune.py`,
`train.py`, `evaluate.py`, `validate.py`, `hybrid.py`) e os resultados em
`reports/` (`2_3_model_report.md`, `2_3_tuning.md`, `2_3_validation.md`,
`2_3_hybrid.md`).

## O vocabulário (o "placar" do porteiro)

- **Taxa de captura (recall):** de todos os atacantes *de verdade*, quantos ele
  barrou? Recall 0,90 = pega 90 de cada 100.
- **Precisão (precision):** de todos que ele barrou, quantos eram *mesmo*
  atacantes? Precisão 0,70 = 30% dos barrados eram inocentes.
- **Taxa de falso alarme (FPR):** de todos os inocentes, quantos foram barrados
  por engano? É o "dano colateral" — caríssimo aqui (barrar pagamento = prejuízo).
- **A gangorra:** esses números brigam. Paranoico barra todo mundo; relaxado não
  barra ninguém. Não existe "perfeito" — existe **escolher o equilíbrio**.
- **A nota geral (PR-AUC):** nota de 0 a 1 que resume o porteiro em todos os
  níveis de rigor. Usamos **PR-AUC** (justa quando atacantes são raros); a ROC-AUC
  dá nota **falsamente alta** nesse cenário.

---

## O que cada resultado nos disse

**1) A nota quase perfeita não foi festa — foi desconfiança.**
Porteiro que parece acertar 100% geralmente está numa fila fácil, ou colando.
> `No projeto →` quem tirou nota ~perfeita (PR-AUC 1,0) foi o **LightGBM**, no
> **teste por separação temporal** (treina nos dias 06–10, prova nos dias 11–12).
> Encontrado ao rodar `train.py` → `reports/2_3_model_report.md`. Os
> hiperparâmetros desse porteiro (nº de árvores=120, profundidade=6, folhas=15)
> foram escolhidos por uma **busca enxuta** em `tune.py` (ver ponto sobre tamanho).

**2) Uma regra boba empatou com o porteiro inteligente.**
Uma regrinha de uma linha ("se insiste na mesma porta, barre") acertou quase
tanto quanto o modelo → **os ataques do teste são óbvios demais**.
> `No projeto →` técnica: comparar o **LightGBM** com um **baseline trivial**
> (regra `diversidade_de_endereços ≤ 2`). Feito no **Teste 1** de `validate.py`
> → `reports/2_3_validation.md`. A regra deu F1 0,96; o modelo, 0,98.

**3) A nota honesta é ~0,92, não 1,0.**
Testando em **várias semanas diferentes** e tirando a média, a nota real apareceu.
> `No projeto →` técnica: **walk-forward** (validação que desliza no tempo,
> `TimeSeriesSplit` com 4 fatias), aplicada ao **LightGBM**. Em `train.py` →
> relatório. Deu PR-AUC 0,92 ± 0,08 (a variação ± mostra que em algumas semanas
> ele vai pior).

**4) Ele estava "colando" pelo crachá.**
Alguns campos (endereço de origem e "impressão digital" de quem chega) quase
entregavam a resposta — decorar nomes em vez de observar comportamento.
> `No projeto →` técnica: **teste A/B de feature** (treinar com e sem o campo
> `país`) + análise que mostrou esses campos sendo "quase o gabarito". Medido em
> `train.py` (comparação com/sem país) e analisado antes da decisão **D12**
> (`docs/DECISIONS.md`). Efeito: no **LightGBM** não mudou nada (ele não precisa
> da cola); na **Regressão Logística** melhorou 10 pontos (ela se apoiava nela).
> Conclusão: **proibimos** os campos de identidade crua como pista.

**5) O porteiro esperto é bem melhor que o simples.**
Pegar esses ataques exige **combinar várias pistas ao mesmo tempo** — o simples
não faz isso.
> `No projeto →` comparação direta **LightGBM × Regressão Logística** na mesma
> tabela de resultados (`train.py` → relatório): F1 0,98 vs 0,67. Cada um com seu
> preparo de dados próprio (`preprocess.py`). Registrado na decisão **D10**.

**6) Ele é cauteloso: quase não barra inocente, mas deixa alguns passarem.**
Erra pouquíssimo contra inocentes, mas escapa ~4% dos atacantes conhecidos.
> `No projeto →` isso é efeito do **ponto de corte** escolhido: pegamos o valor
> que maximiza o equilíbrio **no treino** e aplicamos no teste (função
> `best_f1_threshold` em `evaluate.py`). Resultado do **LightGBM**: precisão 1,0,
> captura 0,96, falso alarme 0,0.

**7) Provamos que não há trapaça no código.**
Embaralhamos o gabarito de propósito; se ainda "acertasse", haveria vazamento.
Ele passou a errar tudo — exatamente o esperado.
> `No projeto →` técnica: **teste de embaralhamento de rótulos** (label-shuffle)
> no **LightGBM**. **Teste 2** de `validate.py`. Nota despencou para ~0,01 →
> **pipeline limpo**.

**8) Ele observa comportamento, não decora rostos.**
Com pessoas nunca vistas, continuou indo bem.
> `No projeto →` técnica: **separação por fonte** (garantir que nenhum IP do
> treino apareça no teste). **Teste 3** de `validate.py`. Captura caiu só de 0,95
> para ~0,75 → o **LightGBM** julga pelo *jeito de agir*. Reforça a decisão D12.

**9) O ponto fraco crítico: não reconhece ataque inédito.**
Escondendo um tipo inteiro de ataque no treino, na prova ele não pegou quase
nenhum.
> `No projeto →` técnica: **esconder uma classe de ataque por vez**
> (leave-one-class-out) no **LightGBM**. **Teste 4** de `validate.py`. Captura
> ≈0 em quase todas → o supervisionado sozinho é insuficiente. Foi esse resultado
> que **motivou mudar a arquitetura** (decisão D14).

**10) A solução: um segundo porteiro que estranha o anormal.**
Ele não estuda bandidos — aprende só o comportamento *normal* e alarma o esquisito,
mesmo inédito. Regra final: barra se o primeiro reconhece OU o segundo estranha.
> `No projeto →` modelo: **IsolationForest** (200 árvores), treinado **só em
> tráfego benigno**, com alarme regulado para incomodar no máximo 1% dos
> inocentes (percentil 99 do "estranhamento"). Combinado com o LightGBM por um
> **OU lógico** em `hybrid.py` → `reports/2_3_hybrid.md` (decisão D14). A captura
> de ataques inéditos saltou de ~0% para 67–98%, ao custo de ~0,6% de falso alarme.

**11) Um ataque ainda escapa dos dois.**
O que **finge ser usuário legítimo** (devagar, sem erros) não é reconhecido pelo
primeiro (é novo) nem estranhado pelo segundo (parece normal).
> `No projeto →` é a classe `api_abuse`, vista no mesmo teste do híbrido
> (`hybrid.py`): captura 0,00 mesmo com os dois porteiros. Mapeado como melhoria
> futura (features de sessão mais longas), conecta com a Parte 3.4.

---

## Sobre o tamanho do porteiro esperto (hiperparâmetros)

Não escolhemos "o mais forte", e sim **o menor que não perde desempenho** —
porque ele precisa caber num ambiente apertado (o edge).
> `No projeto →` técnica: **busca enxuta** testando combinações de tamanho numa
> validação temporal, em `tune.py` → `reports/2_3_tuning.md` (decisão D15).
> Escolhido: 120 árvores, profundidade 6, 15 folhas. Guardamos ainda uma versão
> ~2× menor (só 2% pior) como carta na manga para a etapa de edge (2.4).

## Em uma frase

Temos um **porteiro esperto (LightGBM) cauteloso e competente contra ameaças
conhecidas**, reforçado por um **porteiro do estranho (IsolationForest) que fareja
o inédito**, validados por uma bateria de testes (`validate.py`) que separou
"bom de verdade" de "bom por sorte/bug" — com um limite claro (o ataque
disfarçado) e um ponto de equilíbrio ainda a acertar conforme o custo de cada erro.
