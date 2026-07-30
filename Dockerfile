# ---------------------------------------------------------------------------
# Estágio 1/2: build — converte o modelo de classificação pra ONNX Runtime em
# build-time, não em runtime, assim o container não paga esse custo a cada
# deploy/reinício, só na hora do build (cacheada pelo Docker enquanto
# converter_modelo.py não mudar). Só esse estágio precisa de torch + optimum
# (necessários pra exportar o modelo pra ONNX); nenhum dos dois é copiado pro
# estágio final.
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS build

WORKDIR /app

# Build CPU-only do torch: evita puxar as libs CUDA (a Railway não tem GPU),
# que deixariam esse estágio maior e mais lento à toa (mesmo não indo pra
# imagem final, ele ainda pesa no tempo de build).
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir "optimum[onnxruntime]" transformers

COPY converter_modelo.py .
RUN python converter_modelo.py

# ---------------------------------------------------------------------------
# Estágio 2/2: runtime — só as dependências de produção (sem torch/optimum;
# a classificação roda com onnxruntime puro, ver ia_classificador.py).
# ---------------------------------------------------------------------------
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --from=build /app/modelo_onnx ./modelo_onnx
COPY . .

EXPOSE 8501

CMD streamlit run app.py --server.port ${PORT:-8501} --server.address 0.0.0.0
