"""Classificação de tickets por IA (zero-shot) usando as categorias cadastradas no banco."""

import sqlite3

from transformers import pipeline

MODELO = "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"

_classificador = None


def carregar_modelo():
    """Carrega (ou reaproveita) o pipeline zero-shot. Chamar antecipadamente
    (ex.: com st.cache_resource) evita que o primeiro ticket pague o custo
    de download/carregamento do modelo."""
    global _classificador
    if _classificador is None:
        _classificador = pipeline("zero-shot-classification", model=MODELO)
    return _classificador


def listar_categorias(conn: sqlite3.Connection) -> list[str]:
    cursor = conn.cursor()
    cursor.execute("SELECT nome FROM categoria ORDER BY id")
    return [linha[0] for linha in cursor.fetchall()]


def classificar(descricao: str, conn: sqlite3.Connection) -> tuple[str, float]:
    """Classifica a descrição do ticket em uma das categorias do banco.

    Retorna (nome_categoria, confianca) onde confianca é o score do rótulo
    escolhido (0 a 1) segundo o modelo zero-shot.
    """
    categorias = listar_categorias(conn)
    classificador = carregar_modelo()
    resultado = classificador(descricao, categorias)
    return resultado["labels"][0], float(resultado["scores"][0])
