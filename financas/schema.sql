-- Finanças do Akira — SQLite local, nada sai da máquina.
--
-- Duas fontes alimentam a mesma tabela:
--   1. extrato OFX/CSV  → verdade oficial do banco, chega em lote, atrasado
--   2. e-mail de transação → chega na hora, mas pode faltar ou vir duplicado
--
-- O extrato é a âncora: quando as duas discordam, o extrato vence. Sem essa
-- regra o saldo derreteria com o tempo, porque e-mail perdido não se percebe.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS conta (
    id          INTEGER PRIMARY KEY,
    apelido     TEXT    NOT NULL UNIQUE,      -- "corrente", "cartao"
    instituicao TEXT    NOT NULL,
    tipo        TEXT    NOT NULL DEFAULT 'corrente'
                        CHECK (tipo IN ('corrente','credito','poupanca')),
    ativa       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS transacao (
    id           INTEGER PRIMARY KEY,
    conta_id     INTEGER NOT NULL REFERENCES conta(id),

    data         TEXT    NOT NULL,            -- ISO 8601: 2026-09-21
    valor        INTEGER NOT NULL,            -- CENTAVOS. negativo = saída.
    descricao    TEXT    NOT NULL,            -- como veio do banco, cru
    estabelecimento TEXT,                     -- limpo pelo modelo local

    categoria    TEXT,                        -- ver categoria_regra
    categoria_origem TEXT CHECK (categoria_origem IN ('regra','modelo','manual')),

    -- Procedência: dá para desfazer uma importação inteira sem tocar no resto.
    fonte        TEXT    NOT NULL CHECK (fonte IN ('ofx','csv','email','manual')),
    fonte_ref    TEXT,                        -- FITID do OFX, id da msg do Gmail
    importado_em TEXT    NOT NULL DEFAULT (datetime('now')),

    -- Conciliação: linha de e-mail que o extrato depois confirmou.
    confirmada   INTEGER NOT NULL DEFAULT 0,

    observacao   TEXT
);

-- Idempotência da importação. Reimportar o mesmo OFX não duplica nada:
-- o FITID é único por instituição, então (conta, fonte_ref) basta.
CREATE UNIQUE INDEX IF NOT EXISTS ix_transacao_origem
    ON transacao (conta_id, fonte_ref)
    WHERE fonte_ref IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_transacao_data      ON transacao (data DESC);
CREATE INDEX IF NOT EXISTS ix_transacao_categoria ON transacao (categoria, data DESC);
CREATE INDEX IF NOT EXISTS ix_transacao_pendente  ON transacao (confirmada)
    WHERE confirmada = 0;

-- Saldo vem do banco, não de soma de transação: extrato parcial daria número
-- errado, e número errado de dinheiro é pior que número nenhum.
CREATE TABLE IF NOT EXISTS saldo (
    id        INTEGER PRIMARY KEY,
    conta_id  INTEGER NOT NULL REFERENCES conta(id),
    data      TEXT    NOT NULL,
    valor     INTEGER NOT NULL,               -- centavos
    fonte     TEXT    NOT NULL,
    UNIQUE (conta_id, data)
);

-- Regra determinística vem antes do modelo: "IFOOD" é sempre comida, e não
-- se gasta uma chamada de LLM (nem se arrisca alucinação) com o que um LIKE
-- resolve. O modelo só decide o que sobra.
CREATE TABLE IF NOT EXISTS categoria_regra (
    id        INTEGER PRIMARY KEY,
    padrao    TEXT    NOT NULL,               -- casado com LIKE, sem acento, maiúsculo
    categoria TEXT    NOT NULL,
    prioridade INTEGER NOT NULL DEFAULT 100,  -- menor roda primeiro
    criada_em TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_regra_prioridade ON categoria_regra (prioridade);

-- Toda importação vira uma linha aqui. Quando um número parecer errado,
-- é isto que responde "de onde veio".
CREATE TABLE IF NOT EXISTS importacao (
    id          INTEGER PRIMARY KEY,
    arquivo     TEXT,
    fonte       TEXT    NOT NULL,
    conta_id    INTEGER REFERENCES conta(id),
    inseridas   INTEGER NOT NULL DEFAULT 0,
    ignoradas   INTEGER NOT NULL DEFAULT 0,   -- duplicatas
    periodo_ini TEXT,
    periodo_fim TEXT,
    rodada_em   TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Gasto por categoria e mês — a consulta que o digest faz todo dia.
CREATE VIEW IF NOT EXISTS gasto_mensal AS
SELECT
    substr(t.data, 1, 7)                    AS mes,
    COALESCE(t.categoria, 'sem categoria')  AS categoria,
    COUNT(*)                                AS qtd,
    -SUM(t.valor)                           AS total_centavos
FROM transacao t
WHERE t.valor < 0
GROUP BY mes, categoria;
