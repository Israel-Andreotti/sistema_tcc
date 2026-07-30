"""Converte o modelo de classificação (zero-shot) pra ONNX Runtime e salva em
./modelo_onnx. Roda uma vez em build-time no Docker (ver Dockerfile) ou
manualmente em dev (`python converter_modelo.py`) — depois disso,
ia_classificador.py carrega direto do ONNX via onnxruntime puro, sem precisar
de torch/optimum instalados (só usados aqui, na conversão)."""

import os

from optimum.onnxruntime import ORTModelForSequenceClassification
from transformers import AutoTokenizer

MODELO = "MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli"
DESTINO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "modelo_onnx")


def converter():
    ORTModelForSequenceClassification.from_pretrained(MODELO, export=True).save_pretrained(DESTINO)
    AutoTokenizer.from_pretrained(MODELO).save_pretrained(DESTINO)
    print(f"Modelo convertido e salvo em {DESTINO}")


if __name__ == "__main__":
    converter()
