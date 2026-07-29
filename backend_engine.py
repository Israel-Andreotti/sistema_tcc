import hashlib
import os
import secrets
import threading
import uuid

import libsql_client

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
    linha[0]/linha["campo"]."""
    __slots__ = ("_row", "_colunas")

    def __init__(self, row, colunas):
        self._row = row
        self._colunas = colunas

    def __getitem__(self, chave):
        return self._row[chave]

    def keys(self):
        return self._colunas


class _Cursor:
    """Imita o pedaço da API de sqlite3.Cursor usado neste projeto."""

    def __init__(self, conexao: "_Conexao"):
        self._conexao = conexao
        self._linhas: list[_Linha] = []
        self.lastrowid = None

    def execute(self, sql: str, parametros=()) -> "_Cursor":
        resultado = self._conexao._client.execute(sql, tuple(parametros))
        self._conexao.total_changes += max(resultado.rows_affected, 0)
        self._linhas = [_Linha(linha, resultado.columns) for linha in resultado.rows]
        self.lastrowid = resultado.last_insert_rowid
        return self

    def fetchone(self):
        return self._linhas[0] if self._linhas else None

    def fetchall(self):
        return self._linhas


class _Conexao:
    """Imita o pedaço da API de sqlite3.Connection usado neste projeto, por
    cima do cliente HTTP do Turso — assim o resto do backend_engine.py (e
    ia_classificador.py/urgencia_engine.py) não precisou mudar."""

    def __init__(self, client):
        self._client = client
        self.total_changes = 0

    def execute(self, sql: str, parametros=()) -> _Cursor:
        return _Cursor(self).execute(sql, parametros)

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        # O client HTTP é compartilhado entre chamadas (ver _obter_client) — não
        # faz sentido fechar a conexão a cada função, só reseta o estado local.
        pass


_client: libsql_client.ClientSync | None = None
_client_lock = threading.Lock()


def _obter_client() -> libsql_client.ClientSync:
    """Reaproveita um único client HTTP entre todas as chamadas do processo,
    em vez de abrir/fechar uma conexão nova a cada função — o ClientSync é
    thread-safe (roda seu próprio loop assíncrono num thread dedicado), o que
    é seguro mesmo com várias sessões do Streamlit chamando em paralelo."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = libsql_client.create_client_sync(
                    os.environ["TURSO_DATABASE_URL"],
                    auth_token=os.environ["TURSO_AUTH_TOKEN"],
                )
    return _client


def _conectar() -> _Conexao:
    return _Conexao(_obter_client())


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
    except libsql_client.LibsqlError:
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
    except libsql_client.LibsqlError:
        conn.rollback()
        return False
    finally:
        conn.close()


def excluir_setor(setor_id: int) -> tuple[bool, str]:
    """Exclui o setor (e o SLA vinculado a ele). Bloqueado se houver tickets
    (ativos ou no histórico) apontando para esse setor.

    A checagem é feita explicitamente aqui (em vez de confiar em ON DELETE
    RESTRICT do schema) porque o Turso, via HTTP, não garante que o PRAGMA
    foreign_keys=ON de uma chamada valha pras chamadas seguintes."""
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
    except libsql_client.LibsqlError:
        conn.rollback()
        return False, "Não foi possível excluir o setor."
    finally:
        conn.close()


def obter_sla_setor(setor_id: int) -> dict:
    conn = _conectar()
    try:
        cursor = conn.execute(
            "SELECT categoria_id, tempo_sla_minutos FROM matriz_sla WHERE setor_id = ?",
            (setor_id,),
        )
        return {linha["categoria_id"]: linha["tempo_sla_minutos"] for linha in cursor.fetchall()}
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
    except libsql_client.LibsqlError:
        conn.rollback()
        return False
    finally:
        conn.close()


def listar_tecnicos() -> list[dict]:
    conn = _conectar()
    try:
        cursor = conn.execute("SELECT id, nome FROM tecnico ORDER BY nome")
        return [dict(linha) for linha in cursor.fetchall()]
    finally:
        conn.close()


def listar_tecnicos_completo() -> list[dict]:
    """Igual a listar_tecnicos, mas inclui o username — usado na tela de
    gerenciamento (o restante do app só precisa do nome pra dropdowns)."""
    conn = _conectar()
    try:
        cursor = conn.execute("SELECT id, nome, username FROM tecnico ORDER BY nome")
        return [dict(linha) for linha in cursor.fetchall()]
    finally:
        conn.close()


def autenticar_tecnico(username: str, senha: str) -> dict | None:
    conn = _conectar()
    try:
        tecnico = conn.execute(
            "SELECT id, nome, username, senha_hash, senha_salt FROM tecnico WHERE username = ?",
            (username.strip().lower(),),
        ).fetchone()
        if not tecnico or not tecnico["senha_hash"]:
            return None
        if not _senha_confere(senha, tecnico["senha_hash"], tecnico["senha_salt"]):
            return None
        return {"id": tecnico["id"], "nome": tecnico["nome"], "username": tecnico["username"]}
    finally:
        conn.close()


def criar_tecnico(nome: str, username: str, senha: str) -> int | None:
    conn = _conectar()
    try:
        senha_hash, senha_salt = _hash_senha(senha)
        cursor = conn.execute(
            "INSERT INTO tecnico (nome, username, senha_hash, senha_salt) VALUES (?, ?, ?, ?)",
            (nome.strip(), username.strip().lower(), senha_hash, senha_salt),
        )
        conn.commit()
        return cursor.lastrowid
    except libsql_client.LibsqlError:
        conn.rollback()
        return None
    finally:
        conn.close()


def atualizar_tecnico(tecnico_id: int, nome: str, username: str) -> bool:
    conn = _conectar()
    try:
        conn.execute(
            "UPDATE tecnico SET nome = ?, username = ? WHERE id = ?",
            (nome.strip(), username.strip().lower(), tecnico_id),
        )
        conn.commit()
        return conn.total_changes > 0
    except libsql_client.LibsqlError:
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
    except libsql_client.LibsqlError:
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
    except libsql_client.LibsqlError:
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
        setor = conn.execute("SELECT id, nome FROM setor WHERE id = ?", (setor_id,)).fetchone()
        if not setor:
            return None

        categoria_nome, confianca_ia = ia_classificador.classificar(descricao_chamado, conn)
        categoria = conn.execute(
            "SELECT id, nome FROM categoria WHERE nome = ?", (categoria_nome,)
        ).fetchone()
        if not categoria:
            return None

        resultado_urgencia = urgencia_engine.calcular_urgencia(categoria["id"], setor_id, conn)

        status_novo = conn.execute("SELECT id FROM status_ticket WHERE nome = 'Novo'").fetchone()
        status_id = status_novo["id"] if status_novo else 1

        ticket_id = str(uuid.uuid4())
        cursor = conn.execute("""
            INSERT INTO ticket (
                id, numero, data_criacao, solicitante_nome, solicitante_ramal, solicitante_sala,
                descricao_original, urgencia_calculada, urgencia_score, confianca_ia,
                data_limite_sla, categoria_atribuida_id, setor_id, status_atual_id
            ) VALUES (?, (SELECT COALESCE(MAX(numero), 0) + 1 FROM ticket), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ticket_id, resultado_urgencia["data_criacao"], solicitante_nome, solicitante_ramal,
            solicitante_sala, descricao_chamado, resultado_urgencia["urgencia"],
            resultado_urgencia["score"], confianca_ia, resultado_urgencia["data_limite_sla"],
            categoria["id"], setor_id, status_id,
        ))
        numero = conn.execute("SELECT numero FROM ticket WHERE id = ?", (ticket_id,)).fetchone()["numero"]
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
    except libsql_client.LibsqlError:
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


def _listar_tickets_por_situacao(incluir_terminais: bool) -> list[dict]:
    """Filtra ativos/histórico direto no SQL (WHERE st.nome IN/NOT IN), em vez
    de buscar a tabela inteira e descartar linha em Python — evita trafegar
    ticket concluído/cancelado toda vez que o Painel (que reconsulta sozinho
    a cada 15s) só quer os ativos, por exemplo."""
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
    except libsql_client.LibsqlError:
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
    except libsql_client.LibsqlError:
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
    except libsql_client.LibsqlError:
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
