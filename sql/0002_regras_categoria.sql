-- Ember, migration 0002: tabela de regras de categorizacao.
-- Duas fontes de sinal: a categoria que a propria Pluggy devolve (category/categoryId,
-- pode sumir se for feature paga e o trial acabar) e um padrao de texto na
-- descricao crua, como fallback que sobrevive o trial.
-- Regra do projeto: sem confianca, cai em 'cinza'. Nao adivinhar.
--
-- Regra PESSOAL (seu nome, seu empregador, suas lojas, suas assinaturas, quem divide a casa)
-- NAO entra aqui: vai em data/regras_privadas.json, fora do git (modelo em exemplos/).
-- Esta tabela so tem padrao generico, que vale pra qualquer pessoa no Brasil.

CREATE TABLE IF NOT EXISTS stg.regra_categoria (
    id bigserial PRIMARY KEY,
    padrao_descricao text,
    pluggy_category text,
    categoria text NOT NULL,
    -- null quando a linha é receita, não despesa: essencialidade não se aplica a entrada.
    essencialidade text CHECK (essencialidade IS NULL OR essencialidade IN ('fixo_compromissado', 'variavel_essencial', 'discricionario', 'cinza')),
    escopo_padrao text,
    ignorar_como_transacao boolean NOT NULL DEFAULT false,
    observacao text,
    criado_em timestamptz NOT NULL DEFAULT now()
);

COMMENT ON COLUMN stg.regra_categoria.ignorar_como_transacao IS
    'Pagamento de fatura de cartão e movimentação interna entre contas próprias não são gasto novo, só reconciliação. Marcar true evita contar duas vezes.';

COMMENT ON COLUMN stg.regra_categoria.padrao_descricao IS
    'Padrão estilo LIKE (% como coringa). ATENÇÃO: o Postgres LIKE é sensível a maiúscula/minúscula. Quem consome esta tabela casa esses padrões ignorando caixa; se algum dia isso virar SQL direto, usar ILIKE, nunca LIKE puro: "Pagamento de fatura", em minúsculo, escapa de um LIKE ''%PAGAMENTO%FATURA%''.';

-- Seed: só padrões genéricos de alta confiança. O resto cai em cinza por padrão, não tem linha aqui de propósito.
-- Transferência entre contas próprias NÃO tem linha por nome aqui: o sinal forte é o documento do titular
-- (payer e receiver com o mesmo CPF), configurado em data/regras_privadas.json, com o nome como reserva.

INSERT INTO stg.regra_categoria (padrao_descricao, pluggy_category, categoria, essencialidade, escopo_padrao, ignorar_como_transacao, observacao) VALUES
    ('%PAGAMENTO%FATURA%', 'Credit card payment', 'Fatura de cartão', 'cinza', 'pf', true, 'É reconciliação da fatura já lançada linha a linha, não gasto novo. Ignorar como transação dupla.'),
    ('%Débito Automático%Fatura Cartão%', 'Credit card payment', 'Fatura de cartão', 'cinza', 'pf', true, 'Débito automático da fatura, mesmo caso.'),
    ('%CREDITO CONSIGNADO%', 'Loans and financing', 'Entrada de empréstimo', 'cinza', 'pf', true, 'Dinheiro de dívida entrando, não é receita.'),
    ('%JUROS SALDO DEVEDOR%', 'Interests charged', 'Juros', 'fixo_compromissado', 'pf', false, 'Custo de ficar no vermelho.'),
    ('IOF%', 'Tax on financial operations', 'Imposto sobre operação financeira', 'fixo_compromissado', 'pf', false, NULL),
    ('%MERCADOLIVRE%', NULL, 'Compra online', 'cinza', NULL, false, 'Pode ser pessoal, casa ou trabalho, depende do item. Zona cinza de propósito.'),
    ('%UBER%TRIP%', 'Taxi and ride-hailing', 'Transporte', 'variavel_essencial', 'pf', false, 'Corrida de aplicativo.'),
    ('%IFOOD%', 'Food delivery', 'Alimentacao fora', 'discricionario', 'pf', false, 'Pedido de delivery.'),
    ('%IFD*%', 'Food delivery', 'Alimentacao fora', 'discricionario', 'pf', false, 'Pedido de delivery (descrição abreviada no cartão).')
ON CONFLICT DO NOTHING;
