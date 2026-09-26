# Servidor em casa

Tudo aqui é opcional. O painel, os alertas e o backup rodam no seu computador sem nada disto. Um servidor sempre ligado (um NAS, um mini PC, um notebook velho) serve pra:

- rodar a rotina todo dia sem depender do seu computador estar ligado;
- receber o toque nos botões na hora, pelo webhook;
- ter um ntfy só seu;
- guardar o resultado num Postgres pra consultar com SQL ou Metabase.

O servidor não fica exposto na internet. O celular e o seu computador chegam nele pelo [Tailscale](https://tailscale.com), uma rede privada entre os seus aparelhos. Veja as zonas em [09-seguranca.md](09-seguranca.md).

## Os três arquivos de compose

| Arquivo | Serviço | Porta | Escuta em |
|---|---|---|---|
| `docker-compose.yml` | Postgres 16 | 5432 | só `127.0.0.1` |
| `docker-compose.ntfy.yml` | ntfy próprio | 8081 | `NTFY_BIND`, padrão `127.0.0.1` |
| `docker-compose.scripts.yml` | `ember-scripts`: rotina diária e webhook | 8082 | `EMBER_BIND`, padrão `127.0.0.1` |

As imagens têm versão fixa (`postgres:16.15-alpine`, `binwiederhier/ntfy:v2.28.0`, `python:3.12.14-slim-bookworm`). O Dependabot abre PR semanal quando sai versão nova.

## Passo a passo

1. Instale Docker e Tailscale no servidor. Entre na mesma tailnet do celular e do computador.
2. Descubra o IP do servidor no Tailscale:

   ```sh
   tailscale ip -4
   ```

3. Copie o repositório pro servidor, com o seu `data/` e o seu `.env` (por `scp` pela tailnet, por exemplo). Confira as permissões:

   ```sh
   chmod 600 .env && chmod 700 data
   ```

4. No `.env` do servidor:

   ```
   EMBER_BIND=<IP do Tailscale>
   NTFY_BIND=<IP do Tailscale>            # só se for usar o ntfy próprio
   POSTGRES_PASSWORD=<senha longa e aleatória>
   ALERTA_WEBHOOK_TOKEN=<32+ caracteres>
   ```

5. Suba o que for usar:

   ```sh
   docker compose up -d                                    # Postgres
   docker compose -f docker-compose.ntfy.yml up -d         # ntfy próprio
   docker compose -f docker-compose.scripts.yml up -d --build
   ```

6. Veja o log do agendador:

   ```sh
   docker logs ember-scripts
   ```

   Deve aparecer `webhook dos botoes em <IP>:8082`. Se aparecer `ERRO: ALERTA_WEBHOOK_TOKEN ausente`, o webhook não subiu e só a rotina roda.

## O contêiner dos scripts

- Roda como o usuário `ember` (uid 1000), sem root. O repositório montado em `/app` precisa pertencer a esse uid. Se o dono da pasta no servidor for outro, passe `EMBER_UID` e `EMBER_GID` no build.
- Usa `network_mode: host` pra alcançar o Postgres em `localhost:5432` e servir o webhook no IP do Tailscale.
- Lê e escreve os mesmos arquivos da pasta: `data/` e `.env` ficam no servidor, não na imagem.
- O agendador roda `atualizar.py` todo dia depois de `EMBER_HORA`, no fuso `EMBER_TZ`. Sem `BACKUP_DESTINO`, ele passa `--sem-backup` sozinho.
- Depois, roda `gerar_carga_sql.py` e, se houver `psql` e `POSTGRES_PASSWORD`, carrega `data/carga.sql` no Postgres.
- Quando um passo falha, o log do contêiner diz só o script e o código de saída. A saída de erro, que pode ter dado financeiro, vai pra `data/logs/<data>.log`, com permissão 0600.

## ntfy próprio

1. Defina `NTFY_BASE_URL` (como o celular enxerga o servidor, por exemplo `http://<servidor>.<tailnet>.ts.net:8081`) e `NTFY_BIND`.
2. Suba o compose. Ele nasce fechado (`deny-all`).
3. Crie um usuário e um token dentro do contêiner:

   ```sh
   docker exec -it ember-ntfy ntfy user add --role=admin ember
   docker exec -it ember-ntfy ntfy token add ember
   ```

4. No `.env`: `NTFY_URL` apontando pro servidor e `NTFY_TOKEN` com o token.
5. No app do ntfy no celular, adicione o servidor próprio e entre com o usuário.
6. Pra os botões valerem na hora, `ALERTA_WEBHOOK_URL=http://<servidor>.<tailnet>.ts.net:8082/alerta`.

O tráfego pela tailnet já vai cifrado pelo WireGuard do Tailscale, por isso o ntfy e o webhook falam HTTP simples ali dentro. Não publique essas portas fora da tailnet.

## Postgres

O `docker-compose.yml` sobe o Postgres com as migrations de `sql/` rodando na primeira vez. Ele exige `POSTGRES_PASSWORD` no `.env` e escuta só em `127.0.0.1:5432`: fora do servidor, ninguém chega nele.

| Migration | O que cria |
|---|---|
| `0001_schema_inicial.sql` | os schemas `raw`, `stg`, `mart` e as tabelas de transação |
| `0002_regras_categoria.sql` | `stg.regra_categoria`, só com padrão genérico |
| `0003_mapa_categoria_pluggy.sql` | o mapa de categoria da Pluggy |
| `0004_fluxo_faturas_cartoes.sql` | `mart.fluxo`, `mart.fatura`, `mart.cartao_limite` e as views |
| `0005_papeis.sql` | os papéis `ember_app` e `ember_leitura`, sem login |

A coluna `fonte` é texto livre: é o rótulo de `PLUGGY_ITEM_IDS`, sem lista fixa de bancos no schema.

### Papéis de menor privilégio

O compose cria o superusuário `ember`, que a carga usa no começo. A migration `0005_papeis.sql` cria dois papéis mais fracos, sem login:

| Papel | Pode |
|---|---|
| `ember_app` | ler, inserir e atualizar em `raw`, `stg` e `mart`. Não apaga, não cria tabela |
| `ember_leitura` | só ler o `mart`. É o do Metabase |

Pra ligar, uma vez, conectado como `ember`:

```sql
ALTER ROLE ember_app LOGIN PASSWORD '<senha longa e aleatória>';
ALTER ROLE ember_leitura LOGIN PASSWORD '<outra senha>';
```

Depois troque a carga pra `ember_app`: no `agendador.py` (o `-U ember` e a senha) e na credencial do n8n. O Metabase entra com `ember_leitura`. Pra desligar de novo: `ALTER ROLE ember_app NOLOGIN;`.

## n8n, alternativa de carga

`n8n/carga-diaria.json` é um fluxo que faz uma carga parecida sem os scripts Python: todo dia às 8h, autentica na Pluggy, confere a saúde de cada conexão, baixa os últimos 15 dias e faz upsert em `mart.transacao`.

Pra importar:

1. No ambiente do contêiner do n8n, defina `PLUGGY_ITEM_IDS` (o mesmo formato do `.env`) e `N8N_BLOCK_ENV_ACCESS_IN_NODE=false`.
2. Importe o JSON. Ele vem sem nenhuma credencial anexada.
3. O nó "Autenticar na Pluggy" lê `$credentials.pluggyApi.clientId` e `clientSecret`. Crie uma credencial com o nome `pluggyApi` e esses dois campos, e anexe ao nó.
4. Crie a credencial do Postgres (de preferência com o papel `ember_app`) e anexe ao nó "Upsert em mart.transacao".
5. Rode uma vez à mão e confira as linhas em `mart.transacao`.

O nó "Montar alerta" só monta o aviso de conexão com problema; ligue ele ao destino que quiser. O fluxo grava em `mart.transacao`, não em `mart.fluxo`: a classificação continua sendo dos scripts Python.

Sobre o `N8N_BLOCK_ENV_ACCESS_IN_NODE=false`: ele deixa qualquer nó de código do n8n ler as variáveis de ambiente do contêiner. É por isso que o fluxo consegue ler `PLUGGY_ITEM_IDS`. Em troca, não guarde outros segredos no ambiente desse n8n, e não rode nele fluxos de terceiros que você não leu.

Se o n8n roda em outro stack do Docker, junte o Postgres na rede dele (ou use host networking), senão o n8n não acha o Postgres pelo nome.

Próximo: [08-backup.md](08-backup.md).
