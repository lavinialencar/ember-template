# Home server

Everything here is optional. The dashboard, the alerts and the backup run on your computer without any of this. An always-on server (a NAS, a mini PC, an old laptop) lets you:

- run the routine every day without depending on your computer being on;
- get button taps right away, through the webhook;
- have an ntfy of your own;
- store the result in Postgres, to query with SQL or Metabase.

The server is not exposed to the internet. Your phone and your computer reach it through [Tailscale](https://tailscale.com), a private network between your devices. See the zones in [09-security.md](09-security.md).

## The three compose files

| File | Service | Port | Listens on |
|---|---|---|---|
| `docker-compose.yml` | Postgres 16 | 5432 | only `127.0.0.1` |
| `docker-compose.ntfy.yml` | your own ntfy | 8081 | `NTFY_BIND`, default `127.0.0.1` |
| `docker-compose.scripts.yml` | `ember-scripts`: daily routine and webhook | 8082 | `EMBER_BIND`, default `127.0.0.1` |

The images have pinned versions (`postgres:16.15-alpine`, `binwiederhier/ntfy:v2.28.0`, `python:3.12.14-slim-bookworm`). Dependabot opens a weekly PR when a new version comes out.

## Step by step

1. Install Docker and Tailscale on the server. Join the same tailnet as your phone and computer.
2. Find the server's Tailscale IP:

   ```sh
   tailscale ip -4
   ```

3. Copy the repository to the server, with your `data/` and your `.env` (with `scp` over the tailnet, for example). Check the permissions:

   ```sh
   chmod 600 .env && chmod 700 data
   ```

4. In the server's `.env`:

   ```
   EMBER_BIND=<Tailscale IP>
   NTFY_BIND=<Tailscale IP>               # only if you use your own ntfy
   POSTGRES_PASSWORD=<long random password>
   ALERT_WEBHOOK_TOKEN=<32+ characters>
   ```

5. Start what you need:

   ```sh
   docker compose up -d                                    # Postgres
   docker compose -f docker-compose.ntfy.yml up -d         # your own ntfy
   docker compose -f docker-compose.scripts.yml up -d --build
   ```

6. Check the scheduler log:

   ```sh
   docker logs ember-scripts
   ```

   You should see `button webhook on <IP>:8082`. If you see `ERROR: ALERT_WEBHOOK_TOKEN missing`, the webhook did not start and only the routine runs.

## The scripts container

- It runs as the user `ember` (uid 1000), not root. The repository mounted at `/app` must belong to that uid. If the folder on the server has a different owner, pass `EMBER_UID` and `EMBER_GID` at build time.
- It uses `network_mode: host` to reach Postgres at `localhost:5432` and to serve the webhook on the Tailscale IP.
- It reads and writes the same files in the folder: `data/` and `.env` stay on the server, not in the image.
- The scheduler runs `update.py` every day after `EMBER_TIME`, in the `EMBER_TZ` time zone. Without `BACKUP_DEST`, it passes `--no-backup` on its own.
- Then it runs `build_load_sql.py` and, if `psql` and `POSTGRES_PASSWORD` are available, loads `data/load.sql` into Postgres.
- When a step fails, the container log shows only the script and the exit code. The error output, which may contain financial data, goes to `data/logs/<date>.log`, with permission 0600.

## Your own ntfy

1. Set `NTFY_BASE_URL` (how your phone sees the server, for example `http://<server>.<tailnet>.ts.net:8081`) and `NTFY_BIND`.
2. Start the compose file. It starts locked (`deny-all`).
3. Create a user and a token inside the container:

   ```sh
   docker exec -it ember-ntfy ntfy user add --role=admin ember
   docker exec -it ember-ntfy ntfy token add ember
   ```

4. In `.env`: `NTFY_URL` pointing to the server and `NTFY_TOKEN` with the token.
5. In the ntfy app on your phone, add your own server and log in with the user.
6. For the buttons to take effect right away, set `ALERT_WEBHOOK_URL=http://<server>.<tailnet>.ts.net:8082/alert`.

Traffic over the tailnet is already encrypted by Tailscale's WireGuard, so ntfy and the webhook speak plain HTTP inside it. Do not publish these ports outside the tailnet.

## Postgres

`docker-compose.yml` starts Postgres and runs the migrations in `sql/` the first time. It requires `POSTGRES_PASSWORD` in `.env` and listens only on `127.0.0.1:5432`: nobody outside the server can reach it.

| Migration | What it creates |
|---|---|
| `0001_initial_schema.sql` | the `raw`, `stg` and `mart` schemas and the transaction tables |
| `0002_category_rules.sql` | `stg.category_rule`, with generic patterns only |
| `0003_pluggy_category_map.sql` | the Pluggy (Open Finance data aggregator) category map |
| `0004_flow_bills_cards.sql` | `mart.flow`, `mart.bill`, `mart.card_limit` and the views |
| `0005_roles.sql` | the `ember_app` and `ember_readonly` roles, without login |

The `source` column is free text: it is the label from `PLUGGY_ITEM_IDS`, with no fixed list of banks in the schema.

### Least-privilege roles

The compose file creates the superuser `ember`, which the load uses at first. The `0005_roles.sql` migration creates two weaker roles, without login:

| Role | Can |
|---|---|
| `ember_app` | read, insert and update in `raw`, `stg` and `mart`. It cannot delete or create tables |
| `ember_readonly` | only read `mart`. This is the one for Metabase |

To turn them on, once, connected as `ember`:

```sql
ALTER ROLE ember_app LOGIN PASSWORD '<long random password>';
ALTER ROLE ember_readonly LOGIN PASSWORD '<another password>';
```

Then switch the load to `ember_app`: in `scheduler.py` (the `-U ember` and the password) and in the n8n credential. Metabase logs in with `ember_readonly`. To turn it off again: `ALTER ROLE ember_app NOLOGIN;`.

## n8n, alternative load

`n8n/daily-load.json` is a workflow that does a similar load without the Python scripts: every day at 8am, it authenticates with Pluggy, checks the health of each connection, fetches the last 15 days and upserts into `mart.transactions`.

To import it:

1. In the n8n container environment, set `PLUGGY_ITEM_IDS` (same format as in `.env`) and `N8N_BLOCK_ENV_ACCESS_IN_NODE=false`.
2. Import the JSON. It comes with no credentials attached.
3. The "Authenticate with Pluggy" node reads `$credentials.pluggyApi.clientId` and `clientSecret`. Create a credential named `pluggyApi` with those two fields, and attach it to the node.
4. Create the Postgres credential (preferably with the `ember_app` role) and attach it to the "Upsert into mart.transactions" node.
5. Run it once by hand and check the rows in `mart.transactions`.

The "Build alert" node only builds the alert for a connection with a problem; connect it to whatever destination you want. The workflow writes to `mart.transactions`, not to `mart.flow`: classification is still done by the Python scripts.

About `N8N_BLOCK_ENV_ACCESS_IN_NODE=false`: it lets any n8n code node read the container's environment variables. That is how the workflow reads `PLUGGY_ITEM_IDS`. In exchange, do not keep other secrets in that n8n's environment, and do not run third-party workflows in it that you have not read.

If n8n runs in another Docker stack, add Postgres to its network (or use host networking), or n8n will not find Postgres by name.

Next: [08-backup.md](08-backup.md).
