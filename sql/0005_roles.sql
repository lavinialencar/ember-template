-- Ember, migration 0005: least-privilege roles. It only CREATES the roles, with no login and without touching the
-- "ember" superuser that docker-compose creates: the load keeps running as it does until the manual switch below.
--
-- ember_app       the load (data/load.sql and n8n): reads, inserts and updates in raw, stg and mart. Does not delete,
--                 does not create tables, does not touch the schema (migrations keep running as "ember").
-- ember_readonly  dashboard and Metabase: only reads mart.
--
-- To turn them on (once, as "ember", with a long random password, outside git):
--   ALTER ROLE ember_app LOGIN PASSWORD '<password>';
--   ALTER ROLE ember_readonly LOGIN PASSWORD '<password>';
-- Then switch the load to ember_app: in scheduler.py and in n8n, user ember_app and its password
-- (instead of -U ember and POSTGRES_PASSWORD). Metabase logs in as ember_readonly.
-- To turn it off again: ALTER ROLE ember_app NOLOGIN;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ember_app') THEN
        CREATE ROLE ember_app NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ember_readonly') THEN
        CREATE ROLE ember_readonly NOLOGIN;
    END IF;
END
$$;

GRANT CONNECT ON DATABASE ember TO ember_app, ember_readonly;

GRANT USAGE ON SCHEMA raw, stg, mart TO ember_app;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA raw, stg, mart TO ember_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA raw, stg, mart TO ember_app;  -- the raw bigserial

GRANT USAGE ON SCHEMA mart TO ember_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA mart TO ember_readonly;  -- includes the views

-- a new table created by "ember" in a future migration is born with the same access
ALTER DEFAULT PRIVILEGES FOR ROLE ember IN SCHEMA raw, stg, mart GRANT SELECT, INSERT, UPDATE ON TABLES TO ember_app;
ALTER DEFAULT PRIVILEGES FOR ROLE ember IN SCHEMA raw, stg, mart GRANT USAGE, SELECT ON SEQUENCES TO ember_app;
ALTER DEFAULT PRIVILEGES FOR ROLE ember IN SCHEMA mart GRANT SELECT ON TABLES TO ember_readonly;
