import hashlib
import os
import secrets
import threading
import uuid

import libsql

import ia_classificador
import urgencia_engine

STATUS_CONCLUIDO = "Concluído"
STATUS_CANCELADO = "Cancelado"
STATUS_TERMINAIS = {STATUS_CONCLUIDO, STATUS_CANCELADO}

# Custo do PBKDF2 na criação/verificação de senha de técnico — alto o bastante
# pra dificultar força bruta offline, sem pesar perceptivelmente numa tela de
# login (rodando uma vez por tentativa, não em loop).
_ITERACOES_SENHA = 200_000


def _hash_senha(senha: str, salt_hex: str | None = None) -> tuple[str, str]:
    salt_hex = salt_hex or secrets.token_hex(16)
    hash_hex = hashlib.pbkdf2_hmac(
        "sha256", senha.encode("utf-8"), bytes.fromhex(salt_hex), _ITERACOES_SENHA
    ).hex()
    return hash_hex, salt_hex


def _senha_confere(senha: str, hash_armazenado: str, salt_hex: str) -> bool:
    hash_calculado, _ = _hash_senha(senha, salt_hex)
    return secrets.compare_digest(hash_calculado, hash_armazenado)


class _Linha:
    """Combina acesso por índice e por nome (como sqlite3.Row), pra manter
    compatível o resto do módulo, que usa tanto dict(linha) quanto
    linha[0]/linha["campo"]. A réplica embutida (ver _obter_conexao_nativa)
    devolve tuplas puras, sem acesso por nome — por isso o mapeamento por
    nome é resolvido aqui via _colunas, e não delegado à linha bruta."""
    __slots__ = ("_row", "_colunas")

    def __init__(self, row, colunas):
        self._row = row
        self._colunas = colunas

    def __getitem__(self, chave):
        if isinstance(chave, str):
            return self._row[self._colunas.index(chave)]
        return self._row[chave]

    def keys(self):
        return self._colunas


class _Cursor:
    """Imita o pedaço da API de sqlite3.Cursor usado neste projeto, por cima
    do cursor nativo do libsql (embedded replica)."""

    def __init__(self, conexao: "_Conexao"):
        self._conexao = conexao
        self._cursor_nativo = None

    def execute(self, sql: str, parametros=()) -> "_Cursor":
        self._cursor_nativo = self._conexao._nativa.execute(sql, list(parametros))
        linhas_afetadas = self._cursor_nativo.rowcount
        if linhas_afetadas and linhas_afetadas > 0:
            self._conexao.total_changes += linhas_afetadas
        return self

    def _colunas(self) -> list[str]:
        descricao = self._cursor_nativo.description
        return [coluna[0] for coluna in descricao] if descricao else []

    def fetchone(self):
        linha = self._cursor_nativo.fetchone()
        return _Linha(linha, self._colunas()) if linha is not None else None

    def fetchall(self):
        colunas = self._colunas()
        return [_Linha(linha, colunas) for linha in self._cursor_nativo.fetchall()]

    @property
    def lastrowid(self):
        return self._cursor_nativo.lastrowid


class _Conexao:
    """Imita o pedaço da API de sqlite3.Connection usado neste projeto, por
    cima da conexão nativa do libsql — assim o resto do backend_engine.py (e
    ia_classificador.py/urgencia_engine.py) não precisou mudar."""

    def __init__(self, nativa):
        self._nativa = nativa
        self.total_changes = 0

    def execute(self, sql: str, parametros=()) -> _Cursor:
        return _Cursor(self).execute(sql, parametros)

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def commit(self):
        # Aplica a escrita no primary remoto e sincroniza a réplica local na
        # sequência, pra quem escreveu enxergar o próprio dado imediatamente
        # na próxima leitura (sem esperar o sync_interval em background).
        self._nativa.commit()
        self._nativa.sync()

    def rollback(self):
        self._nativa.rollback()

    def close(self):
        # A conexão embutida é compartilhada entre chamadas (ver
        # _obter_conexao_nativa) — não faz sentido fechar/reabrir (e perder a
        # réplica local sincronizada) a cada função, só reseta o estado local.
        pass


_CAMINHO_REPLICA_LOCAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_turso_replica.db")
_SYNC_INTERVAL_SEGUNDOS = 5.0

_conexao_nativa = None
_conexao_lock = threading.Lock()


def _obter_conexao_nativa():
    """Reaproveita uma única réplica embutida (embedded replica) entre todas
    as chamadas do processo: leituras acontecem no arquivo SQLite local
    (_turso_replica.db, fora do repositório — ver .gitignore), sem round-trip
    de rede, e o libsql sincroniza esse arquivo com o banco remoto do Turso em
    segundo plano a cada _SYNC_INTERVAL_SEGUNDOS. Escritas continuam indo pro
    remoto (ver _Conexao.commit). A libsql-python documenta a Connection como
    thread-safe, o que é necessário aqui já que várias sessões do Streamlit
    podem chamar em paralelo."""
    global _conexao_nativa
    if _conexao_nativa is None:
        with _conexao_lock:
            if _conexao_nativa is None:
                _conexao_nativa = libsql.connect(
                    _CAMINHO_REPLICA_LOCAL,
                    sync_url=os.environ["TURSO_DATABASE_URL"],
                    auth_token=os.environ["TURSO_AUTH_TOKEN"],
                    sync_interval=_SYNC_INTERVAL_SEGUNDOS,
                )
                _conexao_nativa.sync()
    return _conexao_nativa


def _conectar() -> _Conexao:
    return _Conexao(_obter_conexao_nativa())


def listar_setores() -> list[dict]:
    conn = _conectar()
    try:
        cursor = conn.execute("SELECT id, nome, sigla, criticidade_peso FROM setor ORDER BY nome")
        return [dict(linha) for linha in cursor.fetchall()]
    finally:
        conn.close()


def listar_categorias() -> list[dict]:
    conn = _conectar()
    try:
        cursor = conn.execute("SELECT id, nome, peso_base FROM categoria ORDER BY id")
        return [dict(linha) for linha in cursor.fetchall()]
    finally:
        conn.close()


def criar_setor(nome: str, sigla: str, criticidade_peso: int) -> int | None:
    conn = _conectar()
    try:
        cursor = conn.execute(
            "INSERT INTO setor (nome, sigla, criticidade_peso) VALUES (?, ?, ?)",
            (nome, sigla, criticidade_peso),
        )
        conn.commit()
        return cursor.lastrowid
    except ValueError:
        conn.rollback()
        return None
    finally:
        conn.close()


def atualizar_setor(setor_id: int, nome: str, sigla: str, criticidade_peso: int) -> bool:
    conn = _conectar()
    try:
        conn.execute(
            "UPDATE setor SET nome = ?, sigla = ?, criticidade_peso = ? WHERE id = ?",
            (nome, sigla, criticidade_peso, setor_id),
        )
        conn.commit()
        return conn.total_changes > 0
    except ValueError:
        conn.rollback()
        return False
    finally:
        conn.close()


def excluir_setor(setor_id: int) -> tuple[bool, str]:
    """Exclui o setor (e o SLA vinculado a ele). Bloqueado se houver tickets
    (ativos ou no histórico) apontando para esse setor.

    A checagem é feita explicitamente aqui (em vez de confiar em ON DELETE
    RESTRICT do schema) porque a conexão nunca liga PRAGMA foreign_keys=ON —
    isso também dá uma mensagem de erro amigável em vez do erro genérico de
    violação de chave estrangeira."""
    conn = _conectar()
    try:
        tem_ticket = conn.execute(
            "SELECT 1 FROM ticket WHERE setor_id = ? LIMIT 1", (setor_id,)
        ).fetchone()
        if tem_ticket:
            return False, "Não é possível excluir: existem tickets vinculados a este setor. Edite o setor em vez de excluí-lo."

        conn.execute("DELETE FROM matriz_sla WHERE setor_id = ?", (setor_id,))
        conn.execute("DELETE FROM setor WHERE id = ?", (setor_id,))
        conn.commit()
        return True, "Setor excluído com sucesso."
    except ValueError:
        conn.rollback()
        return False, "Não foi possível excluir o setor."
    finally:
        conn.close()


def obter_sla_todos_setores() -> dict[int, dict]:
    """{setor_id: {categoria_id: tempo_sla_minutos}} pra todos os setores de
    uma vez — evita o padrão N+1 de consultar o SLA setor por setor dentro de
    um laço (ver tela_gerenciar_setores em app.py)."""
    conn = _conectar()
    try:
        cursor = conn.execute("SELECT setor_id, categoria_id, tempo_sla_minutos FROM matriz_sla")
        sla_por_setor: dict[int, dict] = {}
        for linha in cursor.fetchall():
            sla_por_setor.setdefault(linha["setor_id"], {})[linha["categoria_id"]] = linha["tempo_sla_minutos"]
        return sla_por_setor
    finally:
        conn.close()


def definir_sla(categoria_id: int, setor_id: int, tempo_sla_minutos: int) -> bool:
    conn = _conectar()
    try:
        conn.execute("""
            INSERT INTO matriz_sla (categoria_id, setor_id, tempo_sla_minutos) VALUES (?, ?, ?)
            ON CONFLICT (categoria_id, setor_id) DO UPDATE SET tempo_sla_minutos = excluded.tempo_sla_minutos
        """, (categoria_id, setor_id, tempo_sla_minutos))
        conn.commit()
        return True
    except ValueError:
        conn.rollback()
        return False
    finally:
        conn.close()


def listar_tecnicos() -> list[dict]:
    """Só técnicos ativos — usada pelo dropdown "Atribuir técnico" do Painel;
    quem saiu da empresa (ativo = 0) não deve aparecer como opção pra novas
    atribuições, mas continua no banco com o histórico intacto."""
    conn = _conectar()
    try:
        cursor = conn.execute("SELECT id, nome FROM tecnico WHERE ativo = 1 ORDER BY nome")
        return [dict(linha) for linha in cursor.fetchall()]
    finally:
        conn.close()


def listar_tecnicos_completo() -> list[dict]:
    """Igual a listar_tecnicos, mas inclui username/is_admin/ativo e também os
    inativos — usado na tela de gerenciamento (o restante do app só precisa
    do nome dos ativos pra dropdowns)."""
    conn = _conectar()
    try:
        cursor = conn.execute("SELECT id, nome, username, is_admin, ativo FROM tecnico ORDER BY nome")
        return [dict(linha) for linha in cursor.fetchall()]
    finally:
        conn.close()


def contar_admins() -> int:
    """Admins ativos — só eles contam pra garantir que sempre sobre alguém
    capaz de logar como admin (ver atualizar_tecnico). Um admin desativado
    não consegue mais logar, então não é proteção real contra ficar sem
    ninguém pra gerenciar o sistema."""
    conn = _conectar()
    try:
        cursor = conn.execute("SELECT COUNT(*) AS total FROM tecnico WHERE is_admin = 1 AND ativo = 1")
        return cursor.fetchone()["total"]
    finally:
        conn.close()


def autenticar_tecnico(username: str, senha: str) -> dict | None:
    conn = _conectar()
    try:
        tecnico = conn.execute(
            "SELECT id, nome, username, is_admin, senha_hash, senha_salt FROM tecnico WHERE username = ? AND ativo = 1",
            (username.strip().lower(),),
        ).fetchone()
        if not tecnico or not tecnico["senha_hash"]:
            return None
        if not _senha_confere(senha, tecnico["senha_hash"], tecnico["senha_salt"]):
            return None
        return {
            "id": tecnico["id"], "nome": tecnico["nome"], "username": tecnico["username"],
            "is_admin": bool(tecnico["is_admin"]),
        }
    finally:
        conn.close()


def criar_tecnico(nome: str, username: str, senha: str, is_admin: bool = False) -> int | None:
    conn = _conectar()
    try:
        senha_hash, senha_salt = _hash_senha(senha)
        cursor = conn.execute(
            "INSERT INTO tecnico (nome, username, senha_hash, senha_salt, is_admin) VALUES (?, ?, ?, ?, ?)",
            (nome.strip(), username.strip().lower(), senha_hash, senha_salt, int(is_admin)),
        )
        conn.commit()
        return cursor.lastrowid
    except ValueError:
        conn.rollback()
        return None
    finally:
        conn.close()


def atualizar_tecnico(tecnico_id: int, nome: str, username: str, is_admin: bool, ativo: bool) -> bool:
    conn = _conectar()
    try:
        # Impede que a mudança (desmarcar Admin ou desmarcar Ativo) zere os
        # admins efetivamente utilizáveis, senão o sistema fica sem ninguém
        # capaz de logar e acessar "Gerenciar Técnicos" (checagem no backend,
        # não só na UI, pra nenhum outro caminho de código conseguir isso sem
        # querer).
        sera_admin_ativo = is_admin and ativo
        if not sera_admin_ativo:
            tecnico_atual = conn.execute(
                "SELECT is_admin, ativo FROM tecnico WHERE id = ?", (tecnico_id,)
            ).fetchone()
            era_admin_ativo = tecnico_atual and tecnico_atual["is_admin"] and tecnico_atual["ativo"]
            if era_admin_ativo and contar_admins() <= 1:
                return False

        conn.execute(
            "UPDATE tecnico SET nome = ?, username = ?, is_admin = ?, ativo = ? WHERE id = ?",
            (nome.strip(), username.strip().lower(), int(is_admin), int(ativo), tecnico_id),
        )
        conn.commit()
        return conn.total_changes > 0
    except ValueError:
        conn.rollback()
        return False
    finally:
        conn.close()


def alterar_propria_senha(tecnico_id: int, senha_atual: str, nova_senha: str) -> bool:
    """Autoatendimento: exige a senha atual, diferente de
    redefinir_senha_tecnico (reset administrativo feito por um admin em nome
    de outro técnico, sem exigir a senha atual — ver tela_gerenciar_tecnicos)."""
    conn = _conectar()
    try:
        tecnico = conn.execute(
            "SELECT senha_hash, senha_salt FROM tecnico WHERE id = ?", (tecnico_id,)
        ).fetchone()
        if not tecnico or not _senha_confere(senha_atual, tecnico["senha_hash"], tecnico["senha_salt"]):
            return False
        senha_hash, senha_salt = _hash_senha(nova_senha)
        conn.execute(
            "UPDATE tecnico SET senha_hash = ?, senha_salt = ? WHERE id = ?",
            (senha_hash, senha_salt, tecnico_id),
        )
        conn.commit()
        return conn.total_changes > 0
    except ValueError:
        conn.rollback()
        return False
    finally:
        conn.close()


def redefinir_senha_tecnico(tecnico_id: int, nova_senha: str) -> bool:
    conn = _conectar()
    try:
        senha_hash, senha_salt = _hash_senha(nova_senha)
        conn.execute(
            "UPDATE tecnico SET senha_hash = ?, senha_salt = ? WHERE id = ?",
            (senha_hash, senha_salt, tecnico_id),
        )
        conn.commit()
        return conn.total_changes > 0
    except ValueError:
        conn.rollback()
        return False
    finally:
        conn.close()


def excluir_tecnico(tecnico_id: int) -> tuple[bool, str]:
    """Exclui o técnico, bloqueado se houver ticket (ativo ou histórico)
    atribuído a ele — mesmo racional de excluir_setor: preferimos barrar aqui
    a confiar no ON DELETE SET NULL do schema, que apagaria silenciosamente o
    vínculo em vez de avisar quem está excluindo."""
    conn = _conectar()
    try:
        tem_ticket = conn.execute(
            "SELECT 1 FROM ticket WHERE tecnico_atribuido_id = ? LIMIT 1", (tecnico_id,)
        ).fetchone()
        if tem_ticket:
            return False, "Não é possível excluir: existem tickets atribuídos a este técnico."

        conn.execute("DELETE FROM tecnico WHERE id = ?", (tecnico_id,))
        conn.commit()
        return True, "Técnico excluído com sucesso."
    except ValueError:
        conn.rollback()
        return False, "Não foi possível excluir o técnico."
    finally:
        conn.close()


def listar_status() -> list[str]:
    conn = _conectar()
    try:
        cursor = conn.execute("SELECT nome FROM status_ticket ORDER BY id")
        return [linha["nome"] for linha in cursor.fetchall()]
    finally:
        conn.close()


def criar_ticket(
    solicitante_nome: str,
    solicitante_ramal: str,
    solicitante_sala: str,
    setor_id: int,
    descricao_chamado: str,
) -> dict | None:
    conn = _conectar()
    try:
        # setor e status "Novo" não têm relação entre si, mas dá pra buscar os
        # dois num único round-trip juntando as tabelas sem condição de junção
        # (cada WHERE filtra a sua própria tabela) — 1 consulta em vez de 2.
        setor = conn.execute(
            """
            SELECT s.id, s.nome, s.criticidade_peso, st.id AS status_novo_id
            FROM setor s, status_ticket st
            WHERE s.id = ? AND st.nome = 'Novo'
            """,
            (setor_id,),
        ).fetchone()
        if not setor:
            return None
        status_id = setor["status_novo_id"] or 1

        categoria_nome, confianca_ia = ia_classificador.classificar(descricao_chamado, conn)

        # categoria + peso_base + SLA da combinação categoria/setor, também
        # numa única consulta (era categoria, peso_base e matriz_sla em três
        # idas ao banco separadas).
        categoria = conn.execute(
            """
            SELECT cat.id, cat.nome, cat.peso_base, sla.tempo_sla_minutos
            FROM categoria cat
            LEFT JOIN matriz_sla sla ON sla.categoria_id = cat.id AND sla.setor_id = ?
            WHERE cat.nome = ?
            """,
            (setor_id, categoria_nome),
        ).fetchone()
        if not categoria:
            return None

        resultado_urgencia = urgencia_engine.calcular_urgencia(
            categoria["peso_base"], setor["criticidade_peso"], categoria["tempo_sla_minutos"]
        )

        ticket_id = str(uuid.uuid4())
        # RETURNING evita uma segunda ida ao banco só pra reler o número que
        # acabou de ser gerado pela subquery de auto-incremento.
        numero = conn.execute("""
            INSERT INTO ticket (
                id, numero, data_criacao, solicitante_nome, solicitante_ramal, solicitante_sala,
                descricao_original, urgencia_calculada, urgencia_score, confianca_ia,
                data_limite_sla, categoria_atribuida_id, setor_id, status_atual_id
            ) VALUES (?, (SELECT COALESCE(MAX(numero), 0) + 1 FROM ticket), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING numero
        """, (
            ticket_id, resultado_urgencia["data_criacao"], solicitante_nome, solicitante_ramal,
            solicitante_sala, descricao_chamado, resultado_urgencia["urgencia"],
            resultado_urgencia["score"], confianca_ia, resultado_urgencia["data_limite_sla"],
            categoria["id"], setor_id, status_id,
        )).fetchone()["numero"]
        conn.commit()

        return {
            "ticket_id": ticket_id,
            "numero": numero,
            "solicitante_nome": solicitante_nome,
            "setor": setor["nome"],
            "descricao": descricao_chamado,
            "categoria_ia": categoria["nome"],
            "confianca_ia": confianca_ia,
            "urgencia": resultado_urgencia["urgencia"],
            "urgencia_score": resultado_urgencia["score"],
            "tempo_sla_minutos": resultado_urgencia["tempo_sla_minutos"],
            "data_limite": resultado_urgencia["data_limite_sla"],
        }
    except ValueError:
        conn.rollback()
        return None
    finally:
        conn.close()


_TICKETS_QUERY_BASE = """
    SELECT t.id, t.numero, t.data_criacao, t.solicitante_nome, t.solicitante_ramal,
           t.solicitante_sala, t.descricao_original, t.urgencia_calculada,
           t.urgencia_score, t.confianca_ia, t.data_limite_sla,
           cat.nome AS categoria, s.nome AS setor, st.nome AS status,
           tec.nome AS tecnico_atribuido
    FROM ticket t
    JOIN categoria cat ON t.categoria_atribuida_id = cat.id
    JOIN setor s ON t.setor_id = s.id
    JOIN status_ticket st ON t.status_atual_id = st.id
    LEFT JOIN tecnico tec ON t.tecnico_atribuido_id = tec.id
"""


def listar_tickets(filtro_status: str | None = None) -> list[dict]:
    conn = _conectar()
    try:
        query = _TICKETS_QUERY_BASE
        parametros = ()
        if filtro_status:
            query += " WHERE st.nome = ?"
            parametros = (filtro_status,)
        query += " ORDER BY t.data_criacao DESC"

        cursor = conn.execute(query, parametros)
        return [dict(linha) for linha in cursor.fetchall()]
    finally:
        conn.close()


def _filtro_cancelados(incluir_cancelados: bool) -> tuple[str, tuple]:
    """Pedaço de JOIN + WHERE compartilhado pelas contagens do Dashboard, pra
    opcionalmente excluir tickets cancelados sem duplicar a lógica em cada
    função — ver o checkbox "Contar tickets cancelados" em tela_dashboard()."""
    if incluir_cancelados:
        return "", ()
    return " JOIN status_ticket st ON t.status_atual_id = st.id WHERE st.nome != ?", (STATUS_CANCELADO,)


def contagem_tickets_por_urgencia(incluir_cancelados: bool = True) -> dict[str, int]:
    """{urgencia: quantidade} pra todo o histórico de tickets — usado no
    Dashboard, que antes buscava a tabela inteira com listar_tickets() só pra
    contar linhas em pandas."""
    conn = _conectar()
    try:
        filtro, parametros = _filtro_cancelados(incluir_cancelados)
        cursor = conn.execute(
            f"SELECT urgencia_calculada, COUNT(*) AS quantidade FROM ticket t{filtro} GROUP BY urgencia_calculada",
            parametros,
        )
        return {linha["urgencia_calculada"]: linha["quantidade"] for linha in cursor.fetchall()}
    finally:
        conn.close()


def contagem_tickets_por_setor(incluir_cancelados: bool = True) -> dict[str, int]:
    conn = _conectar()
    try:
        filtro, parametros = _filtro_cancelados(incluir_cancelados)
        cursor = conn.execute(
            f"""
            SELECT s.nome AS setor, COUNT(*) AS quantidade
            FROM ticket t JOIN setor s ON t.setor_id = s.id{filtro}
            GROUP BY s.nome
            """,
            parametros,
        )
        return {linha["setor"]: linha["quantidade"] for linha in cursor.fetchall()}
    finally:
        conn.close()


def contagem_tickets_por_categoria(incluir_cancelados: bool = True) -> dict[str, int]:
    conn = _conectar()
    try:
        filtro, parametros = _filtro_cancelados(incluir_cancelados)
        cursor = conn.execute(
            f"""
            SELECT c.nome AS categoria, COUNT(*) AS quantidade
            FROM ticket t JOIN categoria c ON t.categoria_atribuida_id = c.id{filtro}
            GROUP BY c.nome
            """,
            parametros,
        )
        return {linha["categoria"]: linha["quantidade"] for linha in cursor.fetchall()}
    finally:
        conn.close()


def _listar_tickets_por_situacao(incluir_terminais: bool) -> list[dict]:
    """Filtra ativos/histórico direto no SQL (WHERE st.nome IN/NOT IN), em vez
    de buscar a tabela inteira e descartar linha em Python — evita trafegar
    ticket concluído/cancelado toda vez que o Painel só quer os ativos, por
    exemplo. Veja também assinatura_tickets_ativos(), usada para detectar
    mudanças sem buscar todos esses campos."""
    conn = _conectar()
    try:
        status = tuple(STATUS_TERMINAIS)
        operador = "IN" if incluir_terminais else "NOT IN"
        placeholders = ", ".join("?" for _ in status)
        query = f"{_TICKETS_QUERY_BASE} WHERE st.nome {operador} ({placeholders}) ORDER BY t.data_criacao DESC"
        cursor = conn.execute(query, status)
        return [dict(linha) for linha in cursor.fetchall()]
    finally:
        conn.close()


def assinatura_tickets_ativos() -> tuple:
    """Retrato leve (id, status, técnico) dos tickets ativos — sem os campos
    pesados de categoria/urgência/SLA — usado só para detectar se algo mudou
    desde a última checagem, sem precisar buscar o ticket inteiro toda vez."""
    conn = _conectar()
    try:
        status = tuple(STATUS_TERMINAIS)
        placeholders = ", ".join("?" for _ in status)
        query = f"""
            SELECT t.id, st.nome AS status, t.tecnico_atribuido_id
            FROM ticket t
            JOIN status_ticket st ON t.status_atual_id = st.id
            WHERE st.nome NOT IN ({placeholders})
        """
        cursor = conn.execute(query, status)
        linhas = cursor.fetchall()
        return tuple(sorted((l["id"], l["status"], l["tecnico_atribuido_id"]) for l in linhas))
    finally:
        conn.close()


def listar_tickets_ativos() -> list[dict]:
    """Tickets que ainda não chegaram a um estado final (aparecem no Painel)."""
    return _listar_tickets_por_situacao(incluir_terminais=False)


def listar_tickets_historico() -> list[dict]:
    """Tickets concluídos ou cancelados (aparecem na tela de Histórico)."""
    return _listar_tickets_por_situacao(incluir_terminais=True)


def concluir_ticket(ticket_id: str) -> bool:
    """Marca o ticket como concluído, movendo-o para o histórico."""
    return atualizar_status(ticket_id, STATUS_CONCLUIDO)


def cancelar_ticket(ticket_id: str) -> bool:
    """Marca o ticket como cancelado, movendo-o para o histórico."""
    return atualizar_status(ticket_id, STATUS_CANCELADO)


def atualizar_status(ticket_id: str, novo_status: str) -> bool:
    conn = _conectar()
    try:
        status = conn.execute("SELECT id FROM status_ticket WHERE nome = ?", (novo_status,)).fetchone()
        if not status:
            return False
        conn.execute(
            "UPDATE ticket SET status_atual_id = ? WHERE id = ?", (status["id"], ticket_id)
        )
        conn.commit()
        return conn.total_changes > 0
    except ValueError:
        conn.rollback()
        return False
    finally:
        conn.close()


def listar_notas(ticket_id: str) -> list[dict]:
    conn = _conectar()
    try:
        cursor = conn.execute(
            "SELECT data_hora, tecnico_nome, texto FROM ticket_nota WHERE ticket_id = ? ORDER BY data_hora ASC, id ASC",
            (ticket_id,),
        )
        return [dict(linha) for linha in cursor.fetchall()]
    finally:
        conn.close()


def adicionar_nota(ticket_id: str, tecnico_nome: str, texto: str) -> bool:
    conn = _conectar()
    try:
        conn.execute(
            "INSERT INTO ticket_nota (ticket_id, tecnico_nome, texto) VALUES (?, ?, ?)",
            (ticket_id, tecnico_nome, texto),
        )
        conn.commit()
        return True
    except ValueError:
        conn.rollback()
        return False
    finally:
        conn.close()


def atribuir_tecnico(ticket_id: str, tecnico_id: int) -> bool:
    """Atribui um técnico ao ticket e move o status para 'Em Atendimento' automaticamente."""
    conn = _conectar()
    try:
        tecnico = conn.execute("SELECT id FROM tecnico WHERE id = ?", (tecnico_id,)).fetchone()
        status_em_atendimento = conn.execute(
            "SELECT id FROM status_ticket WHERE nome = 'Em Atendimento'"
        ).fetchone()
        if not tecnico or not status_em_atendimento:
            return False

        conn.execute(
            "UPDATE ticket SET tecnico_atribuido_id = ?, status_atual_id = ? WHERE id = ?",
            (tecnico_id, status_em_atendimento["id"], ticket_id),
        )
        conn.commit()
        return conn.total_changes > 0
    except ValueError:
        conn.rollback()
        return False
    finally:
        conn.close()


if __name__ == "__main__":
    setores = listar_setores()
    setor_uti = next(s["id"] for s in setores if "Terapia Intensiva" in s["nome"])
    setor_adm = next(s["id"] for s in setores if "Administrativo" in s["nome"])

    t1 = criar_ticket("Dr. Roberto Silva", "4521", "Sala 3 - UTI", setor_uti,
                       "O sistema PEP de Prontuário Eletrônico travou e não consigo prescrever a medicação de urgência para o paciente do leito 3.")
    t2 = criar_ticket("Carlos Souza", "3310", "Financeiro - Sala 2", setor_adm,
                       "Estou tentando logar no sistema de faturamento para fechar os relatórios do mês, mas está dando erro de login e senha.")

    for i, t in enumerate([t1, t2], start=1):
        if t:
            print(f"\n[Caso de Teste {i}]")
            print(f"Solicitante: {t['solicitante_nome']} ({t['setor']})")
            print(f"Categoria (IA): {t['categoria_ia']} (confiança: {t['confianca_ia']:.2f})")
            print(f"Urgência Calculada: {t['urgencia']} (score: {t['urgencia_score']}, SLA: {t['tempo_sla_minutos']} min)")
            print(f"Prazo Limite: {t['data_limite']}")

    tecnicos = listar_tecnicos()
    if t1 and tecnicos:
        ok = atribuir_tecnico(t1["ticket_id"], tecnicos[0]["id"])
        print(f"\nAtribuição de técnico '{tecnicos[0]['nome']}' ao ticket 1: {ok}")
