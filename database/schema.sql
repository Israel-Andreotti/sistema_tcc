-- Habilita o suporte às chaves estrangeiras (No SQLite, precisa ser ativado explicitamente)
PRAGMA foreign_keys = ON;

-- -----------------------------------------------------
-- Tabela: SETOR
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS setor (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL UNIQUE,
    sigla TEXT NOT NULL UNIQUE,
    criticidade_peso INTEGER NOT NULL CHECK (criticidade_peso BETWEEN 1 AND 5)
);

-- -----------------------------------------------------
-- Tabela: TECNICO (lista pré-definida de técnicos de TI que podem ser
-- atribuídos a um ticket)
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS tecnico (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL UNIQUE
);

-- -----------------------------------------------------
-- Tabela: CATEGORIA
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS categoria (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL UNIQUE,
    descricao TEXT,
    peso_base INTEGER NOT NULL CHECK (peso_base BETWEEN 0 AND 100)
);

-- -----------------------------------------------------
-- Tabela: STATUS_TICKET
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS status_ticket (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL UNIQUE
);

-- -----------------------------------------------------
-- Tabela: MATRIZ_SLA (tempo-alvo contratual por categoria+setor)
-- A urgência NÃO é armazenada aqui: ela é calculada dinamicamente pela
-- equação em urgencia_engine.py, combinando peso_base da categoria,
-- criticidade_peso do setor e o tempo_sla_minutos definido aqui.
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS matriz_sla (
    categoria_id INTEGER,
    setor_id INTEGER,
    tempo_sla_minutos INTEGER NOT NULL CHECK (tempo_sla_minutos > 0),
    PRIMARY KEY (categoria_id, setor_id),
    FOREIGN KEY (categoria_id) REFERENCES categoria (id) ON DELETE CASCADE,
    FOREIGN KEY (setor_id) REFERENCES setor (id) ON DELETE CASCADE
);

-- -----------------------------------------------------
-- Tabela: TICKET (Tabela Principal)
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS ticket (
    id TEXT PRIMARY KEY, -- Armazena o UUID gerado pelo Python como string
    data_criacao TEXT DEFAULT (datetime('now', 'localtime')),
    solicitante_nome TEXT NOT NULL,
    solicitante_ramal TEXT,
    solicitante_sala TEXT,
    descricao_original TEXT NOT NULL,
    urgencia_calculada TEXT NOT NULL,
    urgencia_score REAL NOT NULL,
    confianca_ia REAL NOT NULL,
    data_limite_sla TEXT NOT NULL,
    categoria_atribuida_id INTEGER NOT NULL,
    setor_id INTEGER NOT NULL,
    tecnico_atribuido_id INTEGER,
    status_atual_id INTEGER NOT NULL,
    FOREIGN KEY (categoria_atribuida_id) REFERENCES categoria (id) ON DELETE RESTRICT,
    FOREIGN KEY (setor_id) REFERENCES setor (id) ON DELETE RESTRICT,
    FOREIGN KEY (tecnico_atribuido_id) REFERENCES tecnico (id) ON DELETE SET NULL,
    FOREIGN KEY (status_atual_id) REFERENCES status_ticket (id) ON DELETE RESTRICT
);

-- -----------------------------------------------------
-- Tabela: TICKET_NOTA (histórico dos procedimentos adotados pelo técnico
-- durante o atendimento; cada nota fica registrada com data/hora, não é
-- sobrescrita)
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS ticket_nota (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id TEXT NOT NULL,
    data_hora TEXT DEFAULT (datetime('now', 'localtime')),
    tecnico_nome TEXT NOT NULL,
    texto TEXT NOT NULL,
    FOREIGN KEY (ticket_id) REFERENCES ticket (id) ON DELETE CASCADE
);