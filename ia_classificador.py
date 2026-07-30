"""Classificação de tickets por IA (zero-shot) usando as categorias cadastradas no banco.

Roda direto no ONNX Runtime, sem torch nem optimum em produção — o modelo já
vem convertido pra ONNX antes (ver converter_modelo.py e Dockerfile). A
função classificar() reimplementa o essencial do
ZeroShotClassificationPipeline da própria Transformers (probabilidade de
"entailment" de cada rótulo candidato via NLI, normalizada com softmax),
porque o pipeline pronto da lib exige um modelo torch/tf carregado.

MODELO trocou de mDeBERTa-v3-base-mnli-xnli (multilíngue, 12 camadas) pra
multilingual-MiniLMv2-L6-mnli-xnli: mesmo autor, mesma cobertura de 100+
idiomas (destilado do XLM-RoBERTa-large e afinado em MNLI+XNLI), só que com
6 camadas — bem mais rápido e mais leve em CPU, ao custo de um pouco de
acurácia. É a alternativa que o autor recomenda quando velocidade de
inferência importa mais que o último ponto percentual de acurácia.
"""

import hashlib
import os
import re

import numpy as np
import onnxruntime as ort
from transformers import AutoConfig, AutoTokenizer

MODELO = "MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli"
HYPOTHESIS_TEMPLATE = "This example is {}."

_DIR_MODELO_ONNX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "modelo_onnx")

_sessao: ort.InferenceSession | None = None
_tokenizer = None
_id_entailment: int | None = None

# Cache de classificação por hash da descrição normalizada (+ conjunto de
# categorias, pra não reaproveitar um resultado velho se alguém editar as
# categorias): chamados com texto repetido ou muito parecido (ex.: "sistema
# lento", "sistema tá lento") não pagam inferência de novo. Aproximação
# simples de LRU: descarta a entrada mais antiga quando enche.
_CACHE_CLASSIFICACAO: dict[str, tuple[str, float]] = {}
_CACHE_TAMANHO_MAXIMO = 512


def carregar_modelo():
    """Carrega (ou reaproveita) a sessão ONNX Runtime + tokenizer. Chamar
    antecipadamente (ex.: com st.cache_resource) evita que o primeiro ticket
    pague o custo de carregamento do modelo. Espera o modelo já convertido em
    ./modelo_onnx — rode `python converter_modelo.py` uma vez localmente (a
    imagem Docker já faz isso em build-time, ver Dockerfile)."""
    global _sessao, _tokenizer, _id_entailment
    if _sessao is None:
        if not os.path.isdir(_DIR_MODELO_ONNX):
            raise RuntimeError(
                f"Modelo ONNX não encontrado em {_DIR_MODELO_ONNX}. "
                "Rode `python converter_modelo.py` antes de usar a classificação "
                "(a imagem Docker já faz essa conversão em build-time)."
            )
        caminho_modelo = os.path.join(_DIR_MODELO_ONNX, "model.onnx")
        _sessao = ort.InferenceSession(caminho_modelo, providers=["CPUExecutionProvider"])
        _tokenizer = AutoTokenizer.from_pretrained(_DIR_MODELO_ONNX)

        config = AutoConfig.from_pretrained(_DIR_MODELO_ONNX)
        _id_entailment = config.label2id.get("entailment", len(config.label2id) - 1)
    return _sessao


def listar_categorias(conn) -> list[str]:
    cursor = conn.cursor()
    cursor.execute("SELECT nome FROM categoria ORDER BY id")
    return [linha[0] for linha in cursor.fetchall()]


def _normalizar_descricao(descricao: str) -> str:
    return re.sub(r"\s+", " ", descricao.strip().lower())


def _executar_onnx(descricao_normalizada: str, categorias: list[str]) -> tuple[str, float]:
    """Roda a inferência NLI para cada (descrição, categoria) num único lote
    e escolhe a categoria com maior probabilidade de "entailment", igual ao
    ZeroShotClassificationPipeline em modo single-label (multi_label=False)."""
    premissas = [descricao_normalizada] * len(categorias)
    hipoteses = [HYPOTHESIS_TEMPLATE.format(categoria) for categoria in categorias]
    entradas = _tokenizer(
        premissas, hipoteses, truncation="only_first", padding=True, return_tensors="np"
    )

    nome_saida = _sessao.get_outputs()[0].name
    entradas_onnx = {
        entrada.name: entradas[entrada.name].astype(np.int64)
        for entrada in _sessao.get_inputs()
        if entrada.name in entradas
    }
    logits = _sessao.run([nome_saida], entradas_onnx)[0]

    logits_entailment = logits[:, _id_entailment]
    exponenciais = np.exp(logits_entailment - logits_entailment.max())
    probabilidades = exponenciais / exponenciais.sum()

    indice_top = int(np.argmax(probabilidades))
    return categorias[indice_top], float(probabilidades[indice_top])


def classificar(descricao: str, conn) -> tuple[str, float]:
    """Classifica a descrição do ticket em uma das categorias do banco.

    Retorna (nome_categoria, confianca) onde confianca é a probabilidade de
    "entailment" do rótulo escolhido (0 a 1) segundo o modelo zero-shot.
    """
    carregar_modelo()
    categorias = listar_categorias(conn)
    descricao_normalizada = _normalizar_descricao(descricao)

    chave_cache = hashlib.sha256(
        (descricao_normalizada + "|" + "|".join(categorias)).encode("utf-8")
    ).hexdigest()

    resultado_cacheado = _CACHE_CLASSIFICACAO.get(chave_cache)
    if resultado_cacheado is not None:
        return resultado_cacheado

    resultado = _executar_onnx(descricao_normalizada, categorias)

    if len(_CACHE_CLASSIFICACAO) >= _CACHE_TAMANHO_MAXIMO:
        _CACHE_CLASSIFICACAO.pop(next(iter(_CACHE_CLASSIFICACAO)))
    _CACHE_CLASSIFICACAO[chave_cache] = resultado
    return resultado
