"""Classificação de tickets por IA (zero-shot) usando as categorias cadastradas no banco."""

import os

from optimum.onnxruntime import ORTModelForSequenceClassification
from transformers import AutoTokenizer, pipeline

MODELO = "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"

# Em produção (Docker), o modelo já vem convertido pra ONNX Runtime em
# build-time (ver Dockerfile) — a inferência via ONNX Runtime é bem mais
# rápida em CPU do que PyTorch "eager" puro, o que importa numa hospedagem
# com vCPU compartilhado fraco. Localmente esse diretório não existe, então
# a conversão acontece na hora (mais lenta só na primeira chamada).
_DIR_MODELO_ONNX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "modelo_onnx")

_classificador = None


def carregar_modelo():
    """Carrega (ou reaproveita) o pipeline zero-shot. Chamar antecipadamente
    (ex.: com st.cache_resource) evita que o primeiro ticket pague o custo
    de download/carregamento do modelo."""
    global _classificador
    if _classificador is None:
        ja_convertido = os.path.isdir(_DIR_MODELO_ONNX)
        origem = _DIR_MODELO_ONNX if ja_convertido else MODELO
        modelo = ORTModelForSequenceClassification.from_pretrained(origem, export=not ja_convertido)
        tokenizer = AutoTokenizer.from_pretrained(origem)
        _classificador = pipeline("zero-shot-classification", model=modelo, tokenizer=tokenizer)
    return _classificador


def listar_categorias(conn) -> list[str]:
    cursor = conn.cursor()
    cursor.execute("SELECT nome FROM categoria ORDER BY id")
    return [linha[0] for linha in cursor.fetchall()]


def classificar(descricao: str, conn) -> tuple[str, float]:
    """Classifica a descrição do ticket em uma das categorias do banco.

    Retorna (nome_categoria, confianca) onde confianca é o score do rótulo
    escolhido (0 a 1) segundo o modelo zero-shot.
    """
    categorias = listar_categorias(conn)
    classificador = carregar_modelo()
    resultado = classificador(descricao, categorias)
    return resultado["labels"][0], float(resultado["scores"][0])
