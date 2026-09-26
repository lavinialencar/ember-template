# Desenvolver

## Rodar os testes

Os testes usam só `unittest`, só dado sintético e nenhuma rede. Cada um cria uma pasta temporária e nunca toca o seu `data/`.

```sh
python3 -m unittest discover -s tests -v
```

| Arquivo | O que cobre |
|---|---|
| `test_config.py` | `PLUGGY_ITEM_IDS`, precedência do ambiente sobre o `.env`, validação dos dois JSON pessoais |
| `test_clientes_http.py` | paginação da Pluggy, transação malformada, CNAE só com dígitos |
| `test_notificar.py` | resposta dos botões, texto do push sem nome, token que nunca vai pro ntfy.sh, assinatura, estado atômico |
| `test_agendador.py` | bloqueio progressivo, webhook (bind, token, `Content-Length`), erro que vai pro arquivo e não pro log |
| `test_carga_sql.py` | escape de texto hostil e número não finito na carga do Postgres |
| `test_painel_montar.py` | hash da CSP batendo com o script e SRI presente |
| `test_checar_dados_pessoais.py` | a trava de dado pessoal, e o repositório limpo |

Depois dos testes, rode a demo inteira, como o CI faz:

```sh
python3 scripts/gerar_exemplo.py --forcar
python3 scripts/atualizar.py --sem-api --sem-push --sem-backup
```

`--forcar` sobrescreve `data/`. Só use numa cópia do repositório que não tem o seu dado de verdade.

## A trava de dado pessoal

`tools/checar_dados_pessoais.py` varre todo arquivo de texto do repositório (menos `.git/`, `data/`, `__pycache__/`, `.venv/` e `node_modules/`) e falha se achar:

- um termo da denylist;
- um CPF com dígito verificador válido;
- um UUID que não começa com o prefixo falso `00000000-0000-` (itemId de verdade é UUID);
- um e-mail fora de `example.com`, `example.org` e `example.net`;
- um caminho de pasta de usuário do macOS ou de pasta sincronizada do Google Drive.

```sh
python3 tools/checar_dados_pessoais.py
```

A saída diz o arquivo, a linha e o motivo. Nunca repete o termo achado.

### Por que a denylist guarda só hashes

A denylist existe pra impedir que o nome de quem mantém um fork, o empregador, o banco ou um documento vaze num commit. Se a lista guardasse os termos em texto, ela mesma seria o vazamento: qualquer um leria no repositório público exatamente o que se queria esconder.

Por isso ela guarda só o SHA-256 de cada termo. A trava normaliza o texto (minúsculo, sem acento, só `a-z` e `0-9`), calcula o hash de cada palavra e de cada par de palavras vizinhas, e compara com a lista.

Pra acrescentar um termo:

```sh
python3 -c "import hashlib;print(hashlib.sha256(b'termo em minusculo sem acento').hexdigest())"
```

Cole o hash em `DENYLIST`. O termo pode ter uma ou duas palavras.

O limite: hash de palavra comum pode ser descoberto por tentativa (alguém calcula o hash de uma lista de nomes e compara). A denylist protege contra publicar por descuido, não contra quem quer muito descobrir o que está nela. Não ponha na lista nada que seja segredo por si só, como senha ou número de conta.

### Num fork

A denylist deste repositório protege este repositório. No seu fork, troque pelos seus termos: o seu nome, o do seu empregador, o seu CPF, os seus itemIds, o nome da sua cidade se quiser.

## CI

`.github/workflows/ci.yml` roda a cada push e pull request:

1. Em Python 3.10 e 3.12: compila todos os scripts, roda os testes, roda a demo ponta a ponta e confere que `data/painel.html` saiu, e roda a trava de dado pessoal.
2. `gitleaks` no histórico inteiro, procurando segredo.

As actions estão fixadas por SHA, com permissão só de leitura e sem guardar credencial no checkout. O Dependabot (`.github/dependabot.yml`) propõe atualização semanal das actions, das imagens do compose e do `Dockerfile.scripts`.

## Contribuir sem vazar dado

Antes de abrir um pull request:

- [ ] `python3 -m unittest discover -s tests` passa.
- [ ] `python3 tools/checar_dados_pessoais.py` passa.
- [ ] `git status` não mostra nada de `data/`, `.env`, `*.pem` ou `*.cms`.
- [ ] Dado de exemplo é inventado: "Exemplo" e "Modelo" nos nomes, e-mail em `example.com`, UUID começando com `00000000-0000-`, CPF inválido como `12345678900`.
- [ ] Print e captura de tela só da demo (`gerar_exemplo.py`), nunca do seu painel.
- [ ] Issue e pull request sem trecho do seu `data/`, nem "só uma linha", nem com o valor trocado.
- [ ] Regra pessoal (loja, empregador, pessoa) fica no seu `data/regras_privadas.json`. No código entra só regra que vale pra qualquer pessoa no Brasil.

Um gancho local ajuda a não esquecer. Salve em `.git/hooks/pre-commit` e dê permissão de execução:

```sh
#!/bin/sh
python3 tools/checar_dados_pessoais.py && python3 -m unittest discover -s tests
```

Se tiver o `gitleaks` instalado, `gitleaks detect` faz a mesma busca do CI na sua máquina.

## Onde mexer

| Quero mudar | Arquivo |
|---|---|
| uma regra genérica de classificação | `scripts/fluxo.py` (`PADROES`, `MCC_MAP`, `MAPA_PLUGGY`) ou `scripts/enriquecer_cnpj.py` (`CNAE`) |
| um alerta | `scripts/alertas.py`; o texto do push em `scripts/notificar.py` (`TITULOS`) |
| o formato dos JSON pessoais | `scripts/config_privada.py`, os modelos em `exemplos/` e os guias 03 e 04 |
| o painel | `scripts/painel_dados.py` (números) e `scripts/painel_template.html` (visual) |
| o Postgres | uma migration nova em `sql/`, com o número seguinte |

Veja também [CONTRIBUTING.md](../CONTRIBUTING.md).
