-- Ember, migration 0003: mapa de categoria da Pluggy pra essencialidade.
-- A Pluggy devolve `category` em quase todas as transações. Usar como segundo
-- nível de regra (depois do padrão de descrição da migration 0002), só pras
-- categorias onde a essencialidade é confiável sem contexto adicional.
--
-- NÃO adicionar linha pra categoria ambígua. `Taxi and ride-hailing`,
-- `Shopping`, `Services`, `Transfers` genérico ficam de fora de propósito:
-- transporte é o exemplo canônico de zona cinza ("corrida pode ser mercado
-- ou lazer, a natureza não diz qual").
-- Sem linha aqui = cai em cinza, que é o comportamento correto.
--
-- No começo a zona cinza é grande (centenas de linhas por mês, dependendo
-- do volume). O caminho é revisar na mão: cada revisão vira regra nova
-- (aqui, ou em data/regras_privadas.json quando a regra é pessoal),
-- reduzindo a cinza mês a mês. Não é falha do desenho, é o desenho
-- funcionando: as regras aprendem com quem revisa.

INSERT INTO stg.regra_categoria (pluggy_category, categoria, essencialidade, escopo_padrao, ignorar_como_transacao, observacao) VALUES
    ('Groceries', 'Mercado', 'variavel_essencial', 'pf', false, NULL),
    ('Pharmacy', 'Farmácia', 'variavel_essencial', 'pf', false, NULL),
    ('Healthcare', 'Saúde', 'variavel_essencial', 'pf', false, NULL),
    ('Dentist', 'Saúde', 'variavel_essencial', 'pf', false, NULL),
    ('Insurance', 'Seguro', 'fixo_compromissado', 'pf', false, NULL),
    ('Interests charged', 'Juros', 'fixo_compromissado', 'pf', false, 'Custo de ficar no vermelho, redundante com a regra de descrição da migration 0002, mantido como rede de segurança.'),
    ('Late payment and overdraft costs', 'Juros e multa', 'fixo_compromissado', 'pf', false, NULL),
    ('Bank fees', 'Tarifa bancária', 'fixo_compromissado', 'pf', false, NULL),
    ('Tax on financial operations', 'IOF', 'fixo_compromissado', 'pf', false, 'Redundante com a regra de descrição da migration 0002, mantido como rede de segurança.'),
    ('Credit card payment', 'Fatura de cartão', 'cinza', 'pf', true, 'Redundante com a regra de descrição da migration 0002, mantido como rede de segurança.'),
    ('Same person transfer', 'Transferência entre contas próprias', 'cinza', 'pf', true, 'Redundante com a detecção por documento e nome do titular (data/regras_privadas.json), mantido como rede de segurança pela categoria da Pluggy.'),
    ('Proceeds interests and dividends', 'Rendimento', NULL, 'pf', false, 'É receita, não despesa. Essencialidade não se aplica.'),
    ('Income', 'Receita', NULL, 'pf', false, 'É receita, não despesa. Essencialidade não se aplica.')
ON CONFLICT DO NOTHING;
