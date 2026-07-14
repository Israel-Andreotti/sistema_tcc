import os
import sqlite3

DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))
CAMINHO_DB = os.path.join(DIRETORIO_ATUAL, "tcc_tickets.db")
CAMINHO_SCHEMA = os.path.join(DIRETORIO_ATUAL, "schema.sql")
CAMINHO_SEED = os.path.join(DIRETORIO_ATUAL, "seed.sql")


def inicializar_banco():
    if os.path.exists(CAMINHO_DB):
        os.remove(CAMINHO_DB)

    conn = sqlite3.connect(CAMINHO_DB)
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")

    with open(CAMINHO_SCHEMA, "r", encoding="utf-8") as f:
        cursor.executescript(f.read())

    with open(CAMINHO_SEED, "r", encoding="utf-8") as f:
        cursor.executescript(f.read())

    conn.commit()
    conn.close()
    print(f"Banco recriado com sucesso em {CAMINHO_DB}!")


if __name__ == "__main__":
    inicializar_banco()
