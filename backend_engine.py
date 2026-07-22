import os
import sqlite3
import uuid

import ia_classificador
import urgencia_engine

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database", "tcc_tickets.db")

STATUS_CONCLUIDO = "Concluído"
STATUS_CANCELADO = "Cancelado"
STATUS_TERMINAIS = {STATUS_CONCLUIDO, STATUS_CANCELADO}


def _conectar() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


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
    except sqlite3.Error:
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
    except sqlite3.Error:
        conn.rollback()
        return False
    finally:
        conn.close()


def excluir_setor(setor_id: int) -> tuple[bool, str]:
    """Exclui o setor (e o SLA vinculado a ele). Bloqueado se houver tickets
    (ativos ou no histórico) apontando para esse setor."""
    conn = _conectar()
    try:
        conn.execute("DELETE FROM setor WHERE id = ?", (setor_id,))
        conn.commit()
        return True, "Setor excluído com sucesso."
    except sqlite3.IntegrityError:
        conn.rollback()
        return False, "Não é possível excluir: existem tickets vinculados a este setor. Edite o setor em vez de excluí-lo."
    except sqlite3.Error:
        conn.rollback()
        return False, "Não foi possível excluir o setor."
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
    except sqlite3.Error:
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
    except sqlite3.Error:
        conn.rollback()
        return None
    finally:
        conn.close()


def listar_tickets(filtro_status: str | None = None) -> list[dict]:
    conn = _conectar()
    try:
        query = """
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
        parametros = ()
        if filtro_status:
            query += " WHERE st.nome = ?"
            parametros = (filtro_status,)
        query += " ORDER BY t.data_criacao DESC"

        cursor = conn.execute(query, parametros)
        return [dict(linha) for linha in cursor.fetchall()]
    finally:
        conn.close()


def listar_tickets_ativos(filtro_status: str | None = None) -> list[dict]:
    """Tickets que ainda não chegaram a um estado final (aparecem no Painel)."""
    return [t for t in listar_tickets(filtro_status) if t["status"] not in STATUS_TERMINAIS]


def listar_tickets_historico() -> list[dict]:
    """Tickets concluídos ou cancelados (aparecem na tela de Histórico)."""
    return [t for t in listar_tickets() if t["status"] in STATUS_TERMINAIS]


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
    except sqlite3.Error:
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
    except sqlite3.Error:
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
    except sqlite3.Error:
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
