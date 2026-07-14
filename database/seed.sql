-- =====================================================
-- CARGA DE DADOS INICIAIS (SEED)
-- Sistema de Classificação de Tickets com IA e SLA
-- =====================================================

-- Habilita o suporte às chaves estrangeiras
PRAGMA foreign_keys = ON;

-- -----------------------------------------------------
-- 1. Popula a tabela: SETOR
-- -----------------------------------------------------
-- Cadastra setores hospitalares comuns com seus respectivos pesos de criticidade (1 a 5)
INSERT INTO setor (nome, sigla, criticidade_peso) VALUES
('Unidade de Terapia Intensiva', 'UTI', 5),
('Emergência / Pronto Atendimento', 'EME', 5),
('Centro Cirúrgico', 'CC', 5),
('Farmácia Hospitalar', 'FAR', 4),
('Faturamento / Administrativo', 'ADM', 2),
('Recepção / Cadastro', 'REC', 3),
('Tecnologia da Informação', 'TI', 3);

-- -----------------------------------------------------
-- 2. Popula a tabela: CATEGORIA
-- -----------------------------------------------------
-- Esta é a lista padrão que a IA usará para categorizar os chamados com base no texto.
-- peso_base reflete a severidade típica do tipo de problema (0-100), usada na
-- equação de urgência em urgencia_engine.py.
INSERT INTO categoria (nome, descricao, peso_base) VALUES
('Sistemas Hospitalares (PEP/Sigh)', 'Erros de login, lentidão ou falhas em sistemas de Prontuário Eletrônico e Gestão Hospitalar.', 50),
('Acesso à Rede / Internet', 'Problemas com conexão cabo/Wi-Fi, indisponibilidade de internet ou queda de link.', 45),
('Hardware e Computadores', 'Computador que não liga, tela azul, falha de mouse/teclado ou peças danificadas.', 35),
('Contas e Senhas', 'Reset de senha do Active Directory (AD), e-mail bloqueado ou permissão de acesso a pastas compartilhadas.', 30),
('Telefonia e Ramais', 'Telefone IP mudo, falha ao discar, ramal desconfigurado ou sem sinal.', 25),
('Impressoras e Coletores', 'Impressora térmica ou multifuncional que não imprime, atolamento de papel, coletor de dados sem conectar.', 20);

-- -----------------------------------------------------
-- 3. Popula a tabela: STATUS_TICKET
-- -----------------------------------------------------
-- Estados básicos do ciclo de vida de um ticket
INSERT INTO status_ticket (nome) VALUES
('Novo'),
('Em Atendimento'),
('Pendente'),
('Concluído'),
('Cancelado');

-- -----------------------------------------------------
-- 4. Popula a tabela: MATRIZ_SLA
-- -----------------------------------------------------
-- Define o tempo-alvo (em minutos) de atendimento por combinação Categoria + Setor.
-- A urgência não é definida aqui: é calculada pela equação (peso_base + criticidade_peso
-- do setor, ajustados pelo tempo_sla_minutos abaixo).

-- Categoria: Sistemas Hospitalares (id: 1)
INSERT INTO matriz_sla (categoria_id, setor_id, tempo_sla_minutos) VALUES
(1, 1, 30),   -- Sistemas no Setor UTI
(1, 2, 30),   -- Sistemas no Setor Emergência
(1, 3, 30),   -- Sistemas no Setor Centro Cirúrgico
(1, 4, 60),   -- Sistemas no Setor Farmácia
(1, 5, 240),  -- Sistemas no Setor ADM
(1, 6, 120),  -- Sistemas no Setor Recepção (impacta o fluxo de entrada)
(1, 7, 240);  -- Sistemas no Setor TI

-- Categoria: Acesso à Rede / Internet (id: 2)
INSERT INTO matriz_sla (categoria_id, setor_id, tempo_sla_minutos) VALUES
(2, 1, 45),   -- Rede na UTI
(2, 2, 45),   -- Rede na Emergência
(2, 3, 45),   -- Rede no Centro Cirúrgico
(2, 4, 90),   -- Rede na Farmácia
(2, 5, 480),  -- Rede no ADM
(2, 6, 180),  -- Rede na Recepção
(2, 7, 120);  -- Rede na TI

-- Categoria: Hardware e Computadores (id: 3)
INSERT INTO matriz_sla (categoria_id, setor_id, tempo_sla_minutos) VALUES
(3, 1, 45),   -- Computador na UTI
(3, 2, 45),   -- Computador na Emergência
(3, 3, 45),   -- Computador no Centro Cirúrgico
(3, 4, 90),   -- Computador na Farmácia
(3, 5, 360),  -- Computador no ADM
(3, 6, 120),  -- Computador na Recepção
(3, 7, 360);  -- Computador na TI

-- Categoria: Contas e Senhas (id: 4)
INSERT INTO matriz_sla (categoria_id, setor_id, tempo_sla_minutos) VALUES
(4, 1, 60),   -- Senha na UTI
(4, 2, 60),   -- Senha na Emergência
(4, 3, 60),   -- Senha no Centro Cirúrgico
(4, 4, 180),  -- Senha na Farmácia
(4, 5, 480),  -- Senha no ADM
(4, 6, 180),  -- Senha na Recepção
(4, 7, 180);  -- Senha na TI

-- Categoria: Telefonia e Ramais (id: 5)
INSERT INTO matriz_sla (categoria_id, setor_id, tempo_sla_minutos) VALUES
(5, 1, 90),   -- Ramal na UTI
(5, 2, 90),   -- Ramal na Emergência
(5, 3, 90),   -- Ramal no Centro Cirúrgico
(5, 4, 240),  -- Ramal na Farmácia
(5, 5, 720),  -- Ramal no ADM
(5, 6, 240),  -- Ramal na Recepção
(5, 7, 720);  -- Ramal na TI

-- Categoria: Impressoras e Coletores (id: 6)
INSERT INTO matriz_sla (categoria_id, setor_id, tempo_sla_minutos) VALUES
(6, 1, 180),  -- Impressora na UTI
(6, 2, 60),   -- Impressora na Emergência (pulseiras de identificação)
(6, 3, 180),  -- Impressora no Centro Cirúrgico
(6, 4, 60),   -- Impressora na Farmácia (etiquetas de medicamentos)
(6, 5, 720),  -- Impressora no ADM (pode esperar mais)
(6, 6, 60),   -- Impressora na Recepção (etiqueta de fichas)
(6, 7, 720);  -- Impressora na TI

-- -----------------------------------------------------
-- 5. Popula a tabela: TECNICO
-- -----------------------------------------------------
-- Lista pré-definida de técnicos de TI que podem ser atribuídos a um ticket
INSERT INTO tecnico (nome) VALUES
('Thiago Souza'),
('Ana Beatriz'),
('Marcos Lima');
