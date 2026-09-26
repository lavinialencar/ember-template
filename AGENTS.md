# Instruções pra assistentes de código

Vale pra qualquer assistente de IA trabalhando neste repositório ou num fork dele (Claude Code, Codex, Cursor, Gemini CLI e outros).

## Regras que não se dobram

- **Nunca leia, imprima, resuma ou copie nada de `data/` nem do `.env`.** Ali mora o extrato, as regras e o cadastro pessoais, e os segredos. Isso inclui `cat`, `head`, `grep`, abrir no editor e rodar script que imprime o conteúdo. Se precisar de dado pra testar, use a demo numa cópia separada ou os testes.
- **Nunca rode `gerar_exemplo.py --forcar`** na pasta de quem usa o Ember de verdade: ele sobrescreve `data/`.
- **Nunca commite** `data/`, `.env`, `*.pem`, `*.key`, `*.cms` nem `data/painel.html`. Não use `git add -f` nem `git add -A` sem conferir o `git status`.
- **Nunca ponha dado real em código, teste, exemplo, doc, issue ou mensagem de commit.** Dado de exemplo é inventado: "Exemplo" e "Modelo" nos nomes, e-mail em `example.com`, UUID começando com `00000000-0000-`, CPF inválido.
- **Nunca troque um bind pra `0.0.0.0`**, nem sugira abrir porta pra internet.
- **Não chame a API da Pluggy, o ntfy ou o TickTick** sem pedido explícito de quem usa. Os scripts sem `--sem-api` e sem `--sem-push` fazem isso.

## Antes de cada commit

```sh
python3 -m unittest discover -s tests
python3 tools/checar_dados_pessoais.py
```

Os dois precisam passar. Se a trava acusar algo, não contorne: tire o dado.

## Onde as coisas moram

| O quê | Onde |
|---|---|
| regras genéricas de classificação | `scripts/fluxo.py`, `scripts/enriquecer_cnpj.py` |
| regras pessoais | `data/regras_privadas.json` (não leia); modelo em `exemplos/` |
| o que a API não traz | `data/cadastro_manual.json` (não leia); modelo em `exemplos/` |
| validação dos dois JSON pessoais | `scripts/config_privada.py` |
| a rotina, em ordem | `scripts/atualizar.py` |
| alertas e push | `scripts/alertas.py`, `scripts/notificar.py`, `scripts/suspeitas.py` |
| webhook e agendador | `scripts/agendador.py` |
| painel | `scripts/painel_dados.py`, `scripts/painel_template.html`, `scripts/painel_montar.py` |
| Postgres | `sql/`, uma migration nova por mudança |
| guias | `docs/`, numerados; diagramas em `assets/` |

## Estilo

- Python só com biblioteca padrão. Nada de dependência nova.
- Texto de código, comentário e doc em português do Brasil, frase curta.
- O push nunca leva valor, nome de loja, de pessoa, de cartão ou de banco. Mantenha assim.
- Mudou comportamento, atualize o guia em `docs/` no mesmo commit.
