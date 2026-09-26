# Como funciona

![Arquitetura do Ember](../assets/arquitetura.svg)

O Ember é uma rotina que roda uma vez por dia. Ela baixa o que há de novo nos seus bancos, grava em arquivos JSON em `data/`, aplica as regras, gera os alertas, manda o push e monta o painel. No fim, faz um backup cifrado. A ordem exata dos passos está em [02-instalar.md](02-instalar.md#a-rotina-passo-a-passo).

## As peças

| Peça | O que faz | Onde mora |
|---|---|---|
| Pluggy | agregador autorizado no Open Finance; entrega extrato, contas e faturas por API | internet |
| MeuPluggy | app da Pluggy onde você conecta os seus bancos; a sua Application lê essas conexões | internet |
| `scripts/` | a rotina inteira, em Python só com biblioteca padrão | sua máquina |
| `data/` | todo o seu dado, em JSON, fora do git | sua máquina |
| `data/regras_privadas.json` | as suas regras de classificação | sua máquina |
| `data/cadastro_manual.json` | o que a API não traz: dívidas, pontos, recebíveis, dados dos cartões | sua máquina |
| `data/painel.html` | o painel, um arquivo estático | sua máquina |
| ntfy | entrega o push no celular | ntfy.sh ou um servidor seu |
| Postgres, n8n | opcionais, pra quem quer SQL, Metabase ou uma carga alternativa | servidor em casa |

## Fato e dimensão

O erro que mais estraga sistema financeiro caseiro é tratar fato e dimensão como a mesma coisa.

| | Fato | Dimensão |
|---|---|---|
| O que é | transação, fatura | regra, categoria, dívida, cartão, ponto, assinatura |
| Vem de | Pluggy, sozinho | você, à mão |
| Volume | centenas por mês | dezenas no total |
| Muda | quase nunca depois de fechado | raramente, mas muda |
| Mora em | `data/transacoes.json`, `data/faturas.json` | `data/regras_privadas.json`, `data/cadastro_manual.json` |

Por isso o Ember nunca escreve nos seus dois arquivos pessoais. Ele só lê, valida e para com uma mensagem clara se algo estiver errado. É melhor não gerar painel do que gerar um painel errado em silêncio.

## Por que Pluggy com MeuPluggy

Pessoa física não participa do Open Finance direto: precisa de uma instituição autorizada no meio. A Pluggy é essa instituição. O MeuPluggy é o app gratuito dela onde você conecta os seus bancos e escolhe com quais aplicações compartilhar.

O ponto que pesa aqui é o consentimento. A Resolução Conjunta nº 1, de 4 de maio de 2020 (Banco Central e CMN), que regula o Open Finance, diz no art. 40, § 2º, inciso III, que os mecanismos de controle das instituições devem assegurar que as demais instituições envolvidas no compartilhamento não tenham acesso às credenciais que o cliente usa pra se identificar e autenticar. Na prática: quando a conexão é feita pelo Open Finance, você autoriza no app do seu banco, e nem a Pluggy nem o Ember recebem a sua senha. Você revoga quando quiser, no app do banco ou no MeuPluggy.

Isso vale pra conexão feita pelo Open Finance. Se algum banco for conectado por outro meio, confira no próprio MeuPluggy como aquela conexão funciona. Texto oficial: [Resolução Conjunta nº 1/2020](https://normativos.bcb.gov.br/Lists/Normativos/Attachments/51028/Res_Conj_0001_v4_P.pdf).

## Por que o Postgres é opcional

O painel, os alertas e o backup só precisam dos arquivos em `data/`. Uma pessoa gera umas 500 transações por mês; 10 anos disso cabem folgado num JSON.

O Postgres entra quando você quer outra coisa: consultar com SQL, ligar um Metabase ou deixar o n8n gravar enquanto outra ferramenta lê. Aí um banco cliente e servidor faz sentido. O Ember gera `data/carga.sql` e o agendador carrega sozinho. Veja [07-servidor-em-casa.md](07-servidor-em-casa.md).

## As camadas no Postgres

As migrations em `sql/` separam três camadas:

| Camada | O que guarda | Regra |
|---|---|---|
| `raw` | o payload cru da Pluggy, como veio | nunca apagar |
| `stg` | tabelas de apoio tipadas, como `stg.regra_categoria` | só padrão genérico, nunca regra pessoal |
| `mart` | pronto pra consulta: `mart.fluxo`, `mart.fatura`, `mart.cartao_limite` e as views `v_fluxo_mensal` e `v_limite_uso` | é o que o painel externo e o Metabase leem |

As regras de classificação não viram tabela. Elas continuam em `scripts/fluxo.py` e nos seus JSON, porque são lógica com exceções. O Postgres guarda o resultado: uma linha por transação classificada.

## Sem duplicar

A Pluggy pode mudar uma transação depois de entregue: `PENDING` vira `POSTED`, ganha o `billId` da fatura e às vezes troca de `id`. Por isso o Ember não empilha.

- Na rotina diária, `atualizar.py` baixa só a janela recente (25 dias) e as parcelas futuras, e troca essa janela inteira por conta. O que é mais velho que a janela fica como estava.
- Se a paginação da API vier cortada, a janela antiga é mantida, pra não apagar o que não veio.
- No Postgres, `gerar_carga_sql.py` escreve `INSERT ... ON CONFLICT DO UPDATE` com chave `(id, parte)`. Rodar de novo atualiza, não duplica.
- O fluxo do n8n usa outra chave: um hash de conta, data, valor, descrição e número da parcela, com um ordinal pra separar duas transações idênticas no mesmo dia.

## O mês de caixa

Compra no cartão não sai do seu bolso no dia da compra. Sai no vencimento da fatura. Por isso cada linha de `data/fluxo.json` tem `data_caixa`, o mês (AAAA-MM) em que o dinheiro se move de verdade:

- conta corrente: o mês da própria transação;
- cartão: o mês de vencimento da fatura (`billId`);
- cartão sem fatura ainda: a previsão da Pluggy mais o deslocamento típico daquele banco;
- parcela de uma fatura que ainda não abriu: vira `compromisso_futuro`, fora do gasto do mês.

Pagar a fatura na conta vira `neutro`. Assim a compra conta uma vez só, no mês da fatura, e o pagamento não conta de novo.

## Os tipos de fluxo

| `tipo_fluxo` | O que é |
|---|---|
| `gasto` | saída que é consumo seu |
| `receita` | entrada recorrente, como salário |
| `receita_unica` | entrada que não se repete: restituição, venda, rendimento |
| `reembolso` | dinheiro que volta por algo que você pagou por alguém ou por um seguro |
| `divida_entrando` | empréstimo caindo na conta; não é renda |
| `neutro` | transferência entre contas suas, pagamento de fatura |
| `estorno` | crédito que desfaz um gasto |
| `compromisso_futuro` | parcela já contratada que ainda não venceu |

Cada `gasto` ganha também uma essencialidade: `fixo_compromissado`, `variavel_essencial`, `discricionario`, `misto` ou `cinza` (sem regra segura). E um escopo: `pf` (pessoal) ou `pj` (empresa ou projeto pago pelo pessoal, que fica fora do gasto pessoal).

Próximo: [02-instalar.md](02-instalar.md).
