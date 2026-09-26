# Cadastro manual

Algumas coisas a API não traz, ou traz pela metade: dívidas fora do cartão, pontos, quem te deve, o dia de fechamento do cartão, o valor da fatura ainda aberta. Elas vão em `data/cadastro_manual.json`, que você preenche lendo os apps. O Ember só lê esse arquivo, nunca escreve nele.

Modelo com dado inventado: [`exemplos/cadastro_manual.exemplo.json`](../exemplos/cadastro_manual.exemplo.json).

## Formato das datas

| Campo | Formato |
|---|---|
| `lido_em`, `ultima_rotacao`, `prazo_ir` | `AAAA-MM-DD` |
| `proxima`, `expira`, `recebidas` | `DD/MM` (a próxima vez que esse dia cair, hoje ou no futuro) ou `DD/MM/AAAA` |

## Os campos

### `lido_em`

Quando você leu os apps pela última vez. Com mais de 30 dias, o painel mostra "Cadastro manual desatualizado".

### `cartoes[]`

| Campo | Obrigatório | O que é |
|---|---|---|
| `fonte` | sim | o mesmo rótulo de `PLUGGY_ITEM_IDS` |
| `nome` | sim | como o cartão aparece no painel e nos alertas |
| `limite` | não | limite total |
| `fatura_aberta` | não | valor da fatura aberta, lido no app. `null` deixa o Ember estimar pelas compras |
| `fecha`, `vence` | não | dia do fechamento e do vencimento, de 1 a 28 |
| `ultima_rotacao` | não | quando você trocou o número do cartão (ou o virtual) pela última vez |

### `dividas[]`

| Campo | Obrigatório | O que é |
|---|---|---|
| `nome` | sim | nome da dívida |
| `tipo` | não | `contrato` (padrão) ou `informal` |
| `saldo` | um dos dois | quanto falta, se você sabe |
| `parcela` e `parcelas_total` | um dos dois | quando não sabe o saldo; o Ember calcula o que falta com `parcelas_pagas` |
| `parcelas_pagas` | não | padrão 0; não pode passar de `parcelas_total` |
| `proxima` | não | a próxima parcela ou a data combinada |
| `nota` | não | texto livre |

### `recebiveis[]`

Dinheiro que alguém te deve, em parcelas.

| Campo | Obrigatório | O que é |
|---|---|---|
| `nome` | sim | do que se trata |
| `parcela` | sim | valor de cada parcela |
| `parcelas_total` | sim | quantas são |
| `recebidas` | não | lista de datas `DD/MM` das que já caíram; não pode ter mais que `parcelas_total` |
| `nota` | não | texto livre |

### `pontos[]`

| Campo | O que é |
|---|---|
| `programa` | nome do programa (obrigatório) |
| `pts` | saldo em pontos |
| `reais` | quanto vale em reais, pela sua estimativa |
| `expira` | quando o lote mais próximo expira |
| `nota` | texto livre |

### `assinaturas[]`

| Campo | Padrão | O que é |
|---|---|---|
| `nome` | obrigatório | como aparece no painel |
| `contem` | obrigatório | trecho da descrição da cobrança |
| `valor` | `null` | valor mensal |
| `mensal` | `true` | `false` pra anual ou avulsa |
| `so_valor` | `null` | só conta a cobrança com exatamente esse valor |
| `detalhe` | `""` | plano, observação |

### `notas_fiscais`

Pra não chegar na declaração do IR sem nota de despesa dedutível.

| Campo | O que é |
|---|---|
| `prazo_ir` | último dia da declaração, `AAAA-MM-DD` |
| `itens[]` | cada despesa, com `descricao`, `tem_nota` (`true` ou `false`) e `sobe_sozinho` (`true` quando a nota já chega à Receita sem você fazer nada) |

## Exemplo

```json
{
  "lido_em": "2026-01-01",
  "cartoes": [
    {"fonte": "banco_a", "nome": "Banco A", "limite": 6000, "fatura_aberta": null, "fecha": 3, "vence": 10, "ultima_rotacao": null},
    {"fonte": "banco_b", "nome": "Banco B", "limite": 3000, "fatura_aberta": 850.0, "fecha": 20, "vence": 27, "ultima_rotacao": "2026-01-15"}
  ],
  "dividas": [
    {"nome": "Empréstimo pessoal Banco Exemplo", "tipo": "contrato", "parcela": 450.0, "parcelas_total": 12, "parcelas_pagas": 4, "proxima": "10/10", "nota": "débito automático"},
    {"nome": "Financiamento Exemplo", "tipo": "contrato", "saldo": 8200.0}
  ],
  "recebiveis": [
    {"nome": "Venda de equipamento usado", "parcela": 300.0, "parcelas_total": 5, "recebidas": ["21/06", "22/07"]}
  ],
  "pontos": [
    {"programa": "Programa de pontos Exemplo", "pts": 12000, "reais": 180.0, "expira": "15/12"}
  ],
  "assinaturas": [
    {"nome": "Streaming Exemplo", "contem": "streaming exemplo", "valor": 39.9, "mensal": true, "detalhe": "plano padrão"}
  ],
  "notas_fiscais": {
    "prazo_ir": "2027-05-29",
    "itens": [
      {"descricao": "Consulta Clínica Exemplo", "tem_nota": false, "sobe_sozinho": false}
    ]
  }
}
```

## Quem usa o quê

| Bloco | Painel | Alerta |
|---|---|---|
| `cartoes` | nome, limite, fatura aberta | melhor cartão pra comprar hoje, fatura fechando em 7 dias, rotação a cada 6 meses |
| `dividas` | quanto falta pagar | parcela vencendo em até 10 dias |
| `recebiveis` | recebido e a receber | parcela atrasada no mês |
| `pontos` | valor por programa | pontos expirando em até 60 dias |
| `assinaturas` | o que está cobrando | assinatura que parou de cobrar há mais de 40 dias; cobrança mensal fora da lista vira "Assinatura nova?" |
| `notas_fiscais` | | nota faltando, nos 120 dias antes do `prazo_ir` |

## Validação

O arquivo é validado a cada rodada por `validar_cadastro`, em `scripts/config_privada.py`. Campo desconhecido, data fora do formato, dia de fechamento fora de 1 a 28, dívida sem saldo nem parcelas, ou mais parcelas pagas que o total param a rodada com uma mensagem que aponta o campo:

```
data/cadastro_manual.json invalido em dividas[1]: informe saldo, ou parcela e parcelas_total
```

## Rotina sugerida

Uma vez por mês, abra os apps e atualize `fatura_aberta`, os saldos das dívidas, os pontos e as parcelas recebidas. Depois troque o `lido_em` pela data de hoje.

Próximo: [05-painel.md](05-painel.md).
