"""Recria o schema e a carga inicial (schema.sql + seed.sql) no banco remoto
do Turso. Lê TURSO_DATABASE_URL e TURSO_AUTH_TOKEN do ambiente ou, se
ausentes, de .streamlit/secrets.toml (o mesmo arquivo usado pelo app)."""

import os
import tomllib

import libsql_client

DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))
CAMINHO_SCHEMA = os.path.join(DIRETORIO_ATUAL, "schema.sql")
CAMINHO_SEED = os.path.join(DIRETORIO_ATUAL, "seed.sql")
CAMINHO_SECRETS = os.path.join(DIRETORIO_ATUAL, "..", ".streamlit", "secrets.toml")


def _credenciais() -> tuple[str, str]:
    if "TURSO_DATABASE_URL" in os.environ and "TURSO_AUTH_TOKEN" in os.environ:
        return os.environ["TURSO_DATABASE_URL"], os.environ["TURSO_AUTH_TOKEN"]
    with open(CAMINHO_SECRETS, "rb") as f:
        secrets = tomllib.load(f)
    return secrets["TURSO_DATABASE_URL"], secrets["TURSO_AUTH_TOKEN"]

# Ordem de exclusão respeita as dependências (tabelas filhas antes das mães).
TABELAS = ["ticket_nota", "ticket", "matriz_sla", "status_ticket", "categoria", "tecnico", "setor"]


def _statements(caminho: str) -> list[str]:
    # Comentários "--" são removidos antes de dividir por ";": alguns deles têm
    # ponto e vírgula como pontuação normal do português (ex.: "atendimento;
    # cada nota..."), o que quebraria o split se fosse feito no texto bruto.
    with open(caminho, "r", encoding="utf-8") as f:
        linhas_sem_comentario = [linha.split("--", 1)[0] for linha in f]
    texto = "\n".join(linhas_sem_comentario)
    return [
        s.strip() for s in texto.split(";")
        if s.strip() and not s.strip().upper().startswith("PRAGMA")
    ]


def inicializar_banco():
    url, auth_token = _credenciais()
    client = libsql_client.create_client_sync(url, auth_token=auth_token)
    try:
        for tabela in TABELAS:
            client.execute(f"DROP TABLE IF EXISTS {tabela}")
        for statement in _statements(CAMINHO_SCHEMA) + _statements(CAMINHO_SEED):
            client.execute(statement)
    finally:
        client.close()
    print("Banco Turso recriado com sucesso!")


if __name__ == "__main__":
    inicializar_banco()
