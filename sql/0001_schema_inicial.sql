-- Ember, migration 0001: schemas e a tabela fato de transação.
-- Camadas: raw (payload cru da Pluggy), stg (tipado, deduplicado), mart (pronto pro Metabase).
-- Regra: nunca apagar raw.

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS stg;
CREATE SCHEMA IF NOT EXISTS mart;

CREATE TABLE IF NOT EXISTS raw.transacao_pluggy (
    id bigserial PRIMARY KEY,
    item_id text NOT NULL,
    account_id text NOT NULL,
    payload jsonb NOT NULL,
    coletado_em timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_raw_transacao_item ON raw.transacao_pluggy (item_id);
CREATE INDEX IF NOT EXISTS idx_raw_transacao_coletado ON raw.transacao_pluggy (coletado_em);

CREATE TABLE IF NOT EXISTS mart.transacao (
    hash_dedup text PRIMARY KEY,
    pluggy_transaction_id text,
    data date NOT NULL,
    data_competencia date NOT NULL,
    valor numeric(14, 2) NOT NULL,
    descricao_raw text NOT NULL,
    descricao text,
    fonte text NOT NULL,  -- rotulo da conexao, o mesmo de PLUGGY_ITEM_IDS (ex.: banco_a)
    tipo_movimento text NOT NULL CHECK (tipo_movimento IN ('conta', 'cartao_credito')),
    conta_id text NOT NULL,
    categoria text,
    essencialidade text CHECK (essencialidade IN ('fixo_compromissado', 'variavel_essencial', 'discricionario', 'cinza')),
    recorrente boolean,
    cancelavel boolean,
    escopo text,
    projeto text,
    parcela_atual integer,
    parcela_total integer,
    compra_id text,
    bill_id text,
    payload jsonb NOT NULL,
    criado_em timestamptz NOT NULL DEFAULT now(),
    atualizado_em timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_mart_transacao_data ON mart.transacao (data);
CREATE INDEX IF NOT EXISTS idx_mart_transacao_fonte ON mart.transacao (fonte);
CREATE INDEX IF NOT EXISTS idx_mart_transacao_essencialidade ON mart.transacao (essencialidade);
CREATE INDEX IF NOT EXISTS idx_mart_transacao_compra ON mart.transacao (compra_id);
