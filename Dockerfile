FROM python:3.11-slim

WORKDIR /app

# Instala a build CPU-only do torch antes do resto do requirements.txt: evita
# puxar as libs CUDA (a Railway não tem GPU), que deixariam a imagem maior e o
# build mais lento à toa.
COPY requirements.txt .
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501

CMD streamlit run app.py --server.port ${PORT:-8501} --server.address 0.0.0.0
