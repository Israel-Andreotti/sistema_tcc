---
title: Sistema de Tickets de TI
emoji: 🎫
colorFrom: blue
colorTo: green
sdk: streamlit
sdk_version: "1.56.0"
app_file: app.py
python_version: "3.11"
pinned: false
---

# Sistema de Tickets de TI

Sistema de abertura e triagem de chamados de TI com classificação automática por IA
(zero-shot) e cálculo de urgência/SLA por categoria e setor. Backend em SQLite (via
Turso, banco remoto compatível com libSQL).

## Rodando localmente

```bash
pip install -r requirements.txt
streamlit run app.py
```
