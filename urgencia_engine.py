"""Equação de urgência: combina peso da categoria (classificação da IA),
criticidade do setor e o SLA (tempo-alvo em minutos) definido para a
combinação categoria+setor.

score = (peso_base_categoria + criticidade_peso_setor * PESO_SETOR) * FATOR_ESCALA / tempo_sla_minutos

Quanto menor o SLA (prazo mais curto) e maior o peso de categoria/setor,
maior o score. Os limiares abaixo foram calibrados comparando o resultado
da fórmula com a matriz de urgência definida manualmente no seed original.
"""

import datetime

PESO_SETOR = 10
FATOR_ESCALA = 100
SLA_PADRAO_MINUTOS = 180  # usado quando não há regra específica na matriz_sla

LIMIAR_CRITICA = 100
LIMIAR_ALTA = 50
LIMIAR_MEDIA = 20


def _classificar_score(score: float) -> str:
    if score >= LIMIAR_CRITICA:
        return "Crítica"
    if score >= LIMIAR_ALTA:
        return "Alta"
    if score >= LIMIAR_MEDIA:
        return "Média"
    return "Baixa"


def calcular_urgencia(categoria_id: int, setor_id: int, conn) -> dict:
    cursor = conn.cursor()

    cursor.execute("SELECT peso_base FROM categoria WHERE id = ?", (categoria_id,))
    categoria = cursor.fetchone()
    peso_base_categoria = categoria["peso_base"] if categoria else 0

    cursor.execute("SELECT criticidade_peso FROM setor WHERE id = ?", (setor_id,))
    setor = cursor.fetchone()
    criticidade_peso_setor = setor["criticidade_peso"] if setor else 1

    cursor.execute(
        "SELECT tempo_sla_minutos FROM matriz_sla WHERE categoria_id = ? AND setor_id = ?",
        (categoria_id, setor_id),
    )
    regra = cursor.fetchone()
    tempo_sla_minutos = regra["tempo_sla_minutos"] if regra else SLA_PADRAO_MINUTOS

    score = (peso_base_categoria + criticidade_peso_setor * PESO_SETOR) * FATOR_ESCALA / tempo_sla_minutos
    urgencia = _classificar_score(score)

    data_criacao = datetime.datetime.now()
    data_limite_sla = data_criacao + datetime.timedelta(minutes=tempo_sla_minutos)

    return {
        "urgencia": urgencia,
        "score": round(score, 2),
        "tempo_sla_minutos": tempo_sla_minutos,
        "data_criacao": data_criacao.strftime("%Y-%m-%d %H:%M:%S"),
        "data_limite_sla": data_limite_sla.strftime("%Y-%m-%d %H:%M:%S"),
    }
