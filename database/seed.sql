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
('UTI Neonatal', 'UTIN', 5),
('Emergência / Pronto Atendimento', 'EME', 5),
('Bloco Cirúrgico', 'BC', 5),
('Farmácia Hospitalar', 'FAR', 4),
('Administrativo', 'ADM', 2),
('Recepção / Cadastro', 'REC', 3),
('Tecnologia da Informação', 'TI', 3),
('Faturamento', 'FAT', 2),
('Direção Geral', 'DG', 2),
('Engenharia Clínica', 'ENGC', 4),
('Recursos Humanos', 'RH', 2),
('Alojamento Conjunto', 'ALOJ', 4),
('Internação da Mulher', 'INTM', 4),
('Pré Natal de Alto Risco', 'PNAR', 5),
('Psicologia', 'PSI', 3),
('Internação Psiquiátrica', 'PSIQ', 4),
('UCI Neonatal', 'UCIN', 4),
('Controle Operacional', 'CO', 3),
('Manutenção', 'MAN', 2),
('Ensino e Pesquisa', 'EP', 2),
('Banco de Leite', 'BL', 3),
('Banco de Sangue', 'BS', 5),
('Financeiro', 'FIN', 2);

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
('Concluído'),
('Cancelado');

-- -----------------------------------------------------
-- 4. Popula a tabela: MATRIZ_SLA
-- -----------------------------------------------------
-- Define o tempo-alvo (em minutos) de atendimento por combinação Categoria + Setor.
-- A urgência não é definida aqui: é calculada pela equação (peso_base + criticidade_peso
-- do setor, ajustados pelo tempo_sla_minutos abaixo).
--
-- Os 7 setores originais (id 1-7) têm SLA definido caso a caso, com nuances de negócio
-- pontuais (ex.: impressora na Emergência é mais urgente que na UTI, por causa das
-- pulseiras de identificação). Os setores adicionados depois (id 8-23) herdam o SLA
-- "padrão" do setor original que tem o mesmo criticidade_peso, para manter consistência
-- sem precisar inventar uma justificativa individual para cada combinação nova:
--   peso 5 -> mesmo padrão de UTI Neonatal/Emergência/Bloco Cirúrgico
--   peso 4 -> mesmo padrão de Farmácia Hospitalar
--   peso 3 -> mesmo padrão de Recepção / Cadastro
--   peso 2 -> mesmo padrão de Administrativo

-- Categoria: Sistemas Hospitalares (id: 1)
INSERT INTO matriz_sla (categoria_id, setor_id, tempo_sla_minutos) VALUES
(1, 1, 30),   -- Sistemas na UTI Neonatal
(1, 2, 30),   -- Sistemas na Emergência
(1, 3, 30),   -- Sistemas no Bloco Cirúrgico
(1, 4, 60),   -- Sistemas na Farmácia
(1, 5, 240),  -- Sistemas no Administrativo
(1, 6, 120),  -- Sistemas na Recepção (impacta o fluxo de entrada)
(1, 7, 240),  -- Sistemas na TI
(1, 8, 240),  -- Sistemas no Faturamento (peso 2)
(1, 9, 240),  -- Sistemas na Direção Geral (peso 2)
(1, 10, 60),  -- Sistemas na Engenharia Clínica (peso 4)
(1, 11, 240), -- Sistemas em Recursos Humanos (peso 2)
(1, 12, 60),  -- Sistemas no Alojamento Conjunto (peso 4)
(1, 13, 60),  -- Sistemas na Internação da Mulher (peso 4)
(1, 14, 30),  -- Sistemas no Pré Natal de Alto Risco (peso 5)
(1, 15, 120), -- Sistemas em Psicologia (peso 3)
(1, 16, 60),  -- Sistemas na Internação Psiquiátrica (peso 4)
(1, 17, 60),  -- Sistemas na UCI Neonatal (peso 4)
(1, 18, 120), -- Sistemas no Controle Operacional (peso 3)
(1, 19, 240), -- Sistemas na Manutenção (peso 2)
(1, 20, 240), -- Sistemas em Ensino e Pesquisa (peso 2)
(1, 21, 120), -- Sistemas no Banco de Leite (peso 3)
(1, 22, 30),  -- Sistemas no Banco de Sangue (peso 5)
(1, 23, 240); -- Sistemas no Financeiro (peso 2)

-- Categoria: Acesso à Rede / Internet (id: 2)
INSERT INTO matriz_sla (categoria_id, setor_id, tempo_sla_minutos) VALUES
(2, 1, 45),   -- Rede na UTI Neonatal
(2, 2, 45),   -- Rede na Emergência
(2, 3, 45),   -- Rede no Bloco Cirúrgico
(2, 4, 90),   -- Rede na Farmácia
(2, 5, 480),  -- Rede no Administrativo
(2, 6, 180),  -- Rede na Recepção
(2, 7, 120),  -- Rede na TI
(2, 8, 480),  -- Rede no Faturamento
(2, 9, 480),  -- Rede na Direção Geral
(2, 10, 90),  -- Rede na Engenharia Clínica
(2, 11, 480), -- Rede em Recursos Humanos
(2, 12, 90),  -- Rede no Alojamento Conjunto
(2, 13, 90),  -- Rede na Internação da Mulher
(2, 14, 45),  -- Rede no Pré Natal de Alto Risco
(2, 15, 180), -- Rede em Psicologia
(2, 16, 90),  -- Rede na Internação Psiquiátrica
(2, 17, 90),  -- Rede na UCI Neonatal
(2, 18, 180), -- Rede no Controle Operacional
(2, 19, 480), -- Rede na Manutenção
(2, 20, 480), -- Rede em Ensino e Pesquisa
(2, 21, 180), -- Rede no Banco de Leite
(2, 22, 45),  -- Rede no Banco de Sangue
(2, 23, 480); -- Rede no Financeiro

-- Categoria: Hardware e Computadores (id: 3)
INSERT INTO matriz_sla (categoria_id, setor_id, tempo_sla_minutos) VALUES
(3, 1, 45),   -- Computador na UTI Neonatal
(3, 2, 45),   -- Computador na Emergência
(3, 3, 45),   -- Computador no Bloco Cirúrgico
(3, 4, 90),   -- Computador na Farmácia
(3, 5, 360),  -- Computador no Administrativo
(3, 6, 120),  -- Computador na Recepção
(3, 7, 360),  -- Computador na TI
(3, 8, 360),  -- Computador no Faturamento
(3, 9, 360),  -- Computador na Direção Geral
(3, 10, 90),  -- Computador na Engenharia Clínica
(3, 11, 360), -- Computador em Recursos Humanos
(3, 12, 90),  -- Computador no Alojamento Conjunto
(3, 13, 90),  -- Computador na Internação da Mulher
(3, 14, 45),  -- Computador no Pré Natal de Alto Risco
(3, 15, 120), -- Computador em Psicologia
(3, 16, 90),  -- Computador na Internação Psiquiátrica
(3, 17, 90),  -- Computador na UCI Neonatal
(3, 18, 120), -- Computador no Controle Operacional
(3, 19, 360), -- Computador na Manutenção
(3, 20, 360), -- Computador em Ensino e Pesquisa
(3, 21, 120), -- Computador no Banco de Leite
(3, 22, 45),  -- Computador no Banco de Sangue
(3, 23, 360); -- Computador no Financeiro

-- Categoria: Contas e Senhas (id: 4)
INSERT INTO matriz_sla (categoria_id, setor_id, tempo_sla_minutos) VALUES
(4, 1, 60),   -- Senha na UTI Neonatal
(4, 2, 60),   -- Senha na Emergência
(4, 3, 60),   -- Senha no Bloco Cirúrgico
(4, 4, 180),  -- Senha na Farmácia
(4, 5, 480),  -- Senha no Administrativo
(4, 6, 180),  -- Senha na Recepção
(4, 7, 180),  -- Senha na TI
(4, 8, 480),  -- Senha no Faturamento
(4, 9, 480),  -- Senha na Direção Geral
(4, 10, 180), -- Senha na Engenharia Clínica
(4, 11, 480), -- Senha em Recursos Humanos
(4, 12, 180), -- Senha no Alojamento Conjunto
(4, 13, 180), -- Senha na Internação da Mulher
(4, 14, 60),  -- Senha no Pré Natal de Alto Risco
(4, 15, 180), -- Senha em Psicologia
(4, 16, 180), -- Senha na Internação Psiquiátrica
(4, 17, 180), -- Senha na UCI Neonatal
(4, 18, 180), -- Senha no Controle Operacional
(4, 19, 480), -- Senha na Manutenção
(4, 20, 480), -- Senha em Ensino e Pesquisa
(4, 21, 180), -- Senha no Banco de Leite
(4, 22, 60),  -- Senha no Banco de Sangue
(4, 23, 480); -- Senha no Financeiro

-- Categoria: Telefonia e Ramais (id: 5)
INSERT INTO matriz_sla (categoria_id, setor_id, tempo_sla_minutos) VALUES
(5, 1, 90),   -- Ramal na UTI Neonatal
(5, 2, 90),   -- Ramal na Emergência
(5, 3, 90),   -- Ramal no Bloco Cirúrgico
(5, 4, 240),  -- Ramal na Farmácia
(5, 5, 720),  -- Ramal no Administrativo
(5, 6, 240),  -- Ramal na Recepção
(5, 7, 720),  -- Ramal na TI
(5, 8, 720),  -- Ramal no Faturamento
(5, 9, 720),  -- Ramal na Direção Geral
(5, 10, 240), -- Ramal na Engenharia Clínica
(5, 11, 720), -- Ramal em Recursos Humanos
(5, 12, 240), -- Ramal no Alojamento Conjunto
(5, 13, 240), -- Ramal na Internação da Mulher
(5, 14, 90),  -- Ramal no Pré Natal de Alto Risco
(5, 15, 240), -- Ramal em Psicologia
(5, 16, 240), -- Ramal na Internação Psiquiátrica
(5, 17, 240), -- Ramal na UCI Neonatal
(5, 18, 240), -- Ramal no Controle Operacional
(5, 19, 720), -- Ramal na Manutenção
(5, 20, 720), -- Ramal em Ensino e Pesquisa
(5, 21, 240), -- Ramal no Banco de Leite
(5, 22, 90),  -- Ramal no Banco de Sangue
(5, 23, 720); -- Ramal no Financeiro

-- Categoria: Impressoras e Coletores (id: 6)
INSERT INTO matriz_sla (categoria_id, setor_id, tempo_sla_minutos) VALUES
(6, 1, 180),  -- Impressora na UTI Neonatal
(6, 2, 60),   -- Impressora na Emergência (pulseiras de identificação)
(6, 3, 180),  -- Impressora no Bloco Cirúrgico
(6, 4, 60),   -- Impressora na Farmácia (etiquetas de medicamentos)
(6, 5, 720),  -- Impressora no Administrativo (pode esperar mais)
(6, 6, 60),   -- Impressora na Recepção (etiqueta de fichas)
(6, 7, 720),  -- Impressora na TI
(6, 8, 720),  -- Impressora no Faturamento
(6, 9, 720),  -- Impressora na Direção Geral
(6, 10, 60),  -- Impressora na Engenharia Clínica
(6, 11, 720), -- Impressora em Recursos Humanos
(6, 12, 60),  -- Impressora no Alojamento Conjunto
(6, 13, 60),  -- Impressora na Internação da Mulher
(6, 14, 180), -- Impressora no Pré Natal de Alto Risco
(6, 15, 60),  -- Impressora em Psicologia
(6, 16, 60),  -- Impressora na Internação Psiquiátrica
(6, 17, 60),  -- Impressora na UCI Neonatal
(6, 18, 60),  -- Impressora no Controle Operacional
(6, 19, 720), -- Impressora na Manutenção
(6, 20, 720), -- Impressora em Ensino e Pesquisa
(6, 21, 60),  -- Impressora no Banco de Leite
(6, 22, 180), -- Impressora no Banco de Sangue
(6, 23, 720); -- Impressora no Financeiro

-- -----------------------------------------------------
-- 5. Popula a tabela: TECNICO
-- -----------------------------------------------------
-- Lista pré-definida de técnicos de TI que podem ser atribuídos a um ticket.
-- Login inicial de cada um: usuário = username abaixo, senha = "trocar123"
-- (hash PBKDF2 já gerado com esse valor). Trocar a senha na tela "Gerenciar
-- Técnicos" assim que possível.
INSERT INTO tecnico (nome, username, senha_hash, senha_salt) VALUES
('Abel Flore', 'abel.flore', '16f7719fc5b201348ef62d9f9adef2ed84a9b4a68209af9ee33760ffd676c715', 'af58f36a351bb5746e0e909877da6d1b'),
('Alexandre Nunes', 'alexandre.nunes', 'c0d66c989dce5f161e970e5ac0b3dcaf74323e42daa04806bef744a7e198b0b6', 'cf22f706c3d0076e4ff6e0da9be2edc9'),
('Alisson Moraes', 'alisson.moraes', '13445cb0e9d563ac5309ab6bcafc6757724b5ae8c433bbe1f0efa18506f40065', '5b46e2cfe8356bd5d2d37fc4d547aba5'),
('Carlos Alberto', 'carlos.alberto', 'be628164bd7fa544027cf9637d4d1ce392df8409d3279f218090b4f18f8811ea', '8beae0b546bc06efe91a058f8807e954'),
('Carlos Eduardo', 'carlos.eduardo', 'e4d104a8ce4769babc98013d572c56e95aaac09b72cc0a5a7d5aa06ff8b7559e', '582825274389645ef31f34735b179394'),
('Inez Caroline', 'inez.caroline', '887ac5ab480df0a8a1abe2a62fb005ce8e8e146018a85cb3cc3c02619ea5fbf8', 'a809ddee7fcb301b5cf3b696e8edd371'),
('Israel Andreotti', 'israel.andreotti', '5a3f438c5383ec8c05d8403d7d54360f81eec0d50c039c9bdb5817847f53f8c4', 'd34093717196533f26dbd8b76c04536e'),
('Jorge Marinho', 'jorge.marinho', '0fb4bafeb7388dc3c7113ced413c7f80f6a11128d6b5e7af38572a09628fb744', '54ba528ee2f7880306e466ff3250a07f'),
('Rodrigo', 'rodrigo', 'e13899095ec800c263b83c26398232a17adb89fe4c5ac364d6992ab15ef1f169', 'f6ea4696b91f42706229e1a14071ab27');
