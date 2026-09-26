-- Ember, migration 0004: o resultado das regras (fluxo), as faturas e os limites dos cartoes.
-- O gerador de carga (scripts/gerar_carga_sql.py) escreve INSERT ... ON CONFLICT pra estas tabelas.
--
-- Decisao de desenho: as regras de classificacao continuam em scripts/fluxo.py (sao ~150 linhas de logica
-- com excecoes, nao uma tabela). O Postgres guarda o RESULTADO, uma linha por transacao classificada, mais
-- as faturas e os limites. Metabase le daqui. Segredo nunca entra aqui: documento, nome de contraparte e valor
-- de regra privada ficam em data/regras_privadas.json (fora do git). Esta migration cria so as tabelas.

CREATE TABLE IF NOT EXISTS mart.fluxo (
    id text NOT NULL,                          -- id da transacao na Pluggy
    parte integer NOT NULL DEFAULT 0,          -- uma transacao pode virar 2+ linhas (regra de divisao: um Pix meio neutro, meio gasto)
    data date NOT NULL,
    data_caixa char(7) NOT NULL,               -- AAAA-MM em que o dinheiro se move (cartao = vencimento da fatura)
    fonte text NOT NULL,                       -- rotulo da conexao, o mesmo de PLUGGY_ITEM_IDS
    conta text,
    descricao text,
    valor numeric(14, 2) NOT NULL,
    categoria text,
    essencialidade text CHECK (essencialidade IS NULL OR essencialidade IN ('fixo_compromissado', 'variavel_essencial', 'discricionario', 'cinza', 'misto')),
    escopo text,
    motivo text,                               -- por que a regra decidiu assim; e o que se revisa na zona cinza
    categoria_pluggy text,
    cartao boolean NOT NULL DEFAULT false,
    tipo_fluxo text NOT NULL CHECK (tipo_fluxo IN ('gasto', 'receita', 'receita_unica', 'reembolso', 'divida_entrando',
                                                     'neutro', 'estorno', 'compromisso_futuro')),
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id, parte)
);

CREATE INDEX IF NOT EXISTS idx_mart_fluxo_caixa ON mart.fluxo (data_caixa, tipo_fluxo);
CREATE INDEX IF NOT EXISTS idx_mart_fluxo_fonte ON mart.fluxo (fonte, data);
CREATE INDEX IF NOT EXISTS idx_mart_fluxo_cinza ON mart.fluxo (essencialidade) WHERE essencialidade = 'cinza';

CREATE TABLE IF NOT EXISTS mart.fatura (
    id text PRIMARY KEY,                       -- bill id da Pluggy
    fonte text NOT NULL,
    vencimento date NOT NULL,
    fechamento date,
    total numeric(14, 2) NOT NULL,
    pagamento_minimo numeric(14, 2),
    permite_parcelar boolean,
    encargos numeric(14, 2) NOT NULL DEFAULT 0, -- soma de financeCharges: juros, multa e IOF do rotativo
    atualizado_em timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_mart_fatura_venc ON mart.fatura (fonte, vencimento);

CREATE TABLE IF NOT EXISTS mart.cartao_limite (
    conta_id text PRIMARY KEY,
    fonte text NOT NULL,
    nome text,
    limite numeric(14, 2),
    disponivel numeric(14, 2),                 -- pode ser negativo: cartao acima do limite
    pagamento_minimo numeric(14, 2),
    vencimento date,
    lido_em date NOT NULL
);

-- O que o painel de tela cheia mais pede: mes de caixa por tipo, sem o neutro (transferencia entre contas proprias).
CREATE OR REPLACE VIEW mart.v_fluxo_mensal AS
SELECT data_caixa, tipo_fluxo, escopo, categoria, essencialidade,
       sum(valor) AS total, count(*) AS linhas
FROM mart.fluxo
WHERE tipo_fluxo <> 'neutro'
GROUP BY data_caixa, tipo_fluxo, escopo, categoria, essencialidade;

-- Uso do limite em %, direto da Pluggy, sem estimar.
CREATE OR REPLACE VIEW mart.v_limite_uso AS
SELECT fonte, nome, limite, disponivel,
       round(100 * (1 - disponivel / nullif(limite, 0)), 1) AS uso_pct,
       lido_em
FROM mart.cartao_limite;
