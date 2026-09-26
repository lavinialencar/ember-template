-- Ember, migration 0005: papeis de menor privilegio. So CRIA os papeis, sem login e sem mexer no
-- superusuario "ember" que o docker-compose cria: a carga continua como esta ate a troca manual abaixo.
--
-- ember_app      a carga (data/carga.sql e o n8n): le, insere e atualiza em raw, stg e mart. Nao apaga,
--                nao cria tabela, nao mexe em schema (migration continua com o "ember").
-- ember_leitura  painel e Metabase: so le o mart.
--
-- Pra ligar (uma vez, como "ember", com senha longa e aleatoria, fora do git):
--   ALTER ROLE ember_app LOGIN PASSWORD '<senha>';
--   ALTER ROLE ember_leitura LOGIN PASSWORD '<senha>';
-- Depois trocar a carga pra ember_app: no agendador.py e no n8n, usuario ember_app e a senha dele
-- (no lugar de -U ember e POSTGRES_PASSWORD). O Metabase entra com ember_leitura.
-- Pra desligar de novo: ALTER ROLE ember_app NOLOGIN;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ember_app') THEN
        CREATE ROLE ember_app NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ember_leitura') THEN
        CREATE ROLE ember_leitura NOLOGIN;
    END IF;
END
$$;

GRANT CONNECT ON DATABASE ember TO ember_app, ember_leitura;

GRANT USAGE ON SCHEMA raw, stg, mart TO ember_app;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA raw, stg, mart TO ember_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA raw, stg, mart TO ember_app;  -- o bigserial do raw

GRANT USAGE ON SCHEMA mart TO ember_leitura;
GRANT SELECT ON ALL TABLES IN SCHEMA mart TO ember_leitura;  -- inclui as views

-- tabela nova criada pelo "ember" numa migration futura ja nasce com o mesmo acesso
ALTER DEFAULT PRIVILEGES FOR ROLE ember IN SCHEMA raw, stg, mart GRANT SELECT, INSERT, UPDATE ON TABLES TO ember_app;
ALTER DEFAULT PRIVILEGES FOR ROLE ember IN SCHEMA raw, stg, mart GRANT USAGE, SELECT ON SEQUENCES TO ember_app;
ALTER DEFAULT PRIVILEGES FOR ROLE ember IN SCHEMA mart GRANT SELECT ON TABLES TO ember_leitura;
