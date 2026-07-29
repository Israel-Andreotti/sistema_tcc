FROM python:3.11-slim

WORKDIR /app

# Instala a build CPU-only do torch antes do resto do requirements.txt: evita
# puxar as libs CUDA (a Railway não tem GPU), que deixariam a imagem maior e o
# build mais lento à toa.
COPY requirements.txt .
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

# Converte o modelo de classificação pra ONNX Runtime em build-time, não em
# runtime: assim o container não paga esse custo de conversão a cada deploy
# ou reinício, só na hora do build (cacheada pelo Docker enquanto o
# requirements.txt não mudar). ia_classificador.py detecta esse diretório e
# carrega direto dele.
RUN python -c "from optimum.onnxruntime import ORTModelForSequenceClassification; from transformers import AutoTokenizer; modelo_id = 'MoritzLaurer/mDeBERTa-v3-base-mnli-xnli'; destino = '/app/modelo_onnx'; ORTModelForSequenceClassification.from_pretrained(modelo_id, export=True).save_pretrained(destino); AutoTokenizer.from_pretrained(modelo_id).save_pretrained(destino)"

COPY . .

EXPOSE 8501

CMD streamlit run app.py --server.port ${PORT:-8501} --server.address 0.0.0.0
