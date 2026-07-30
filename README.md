# Sistema de Tickets de TI

Sistema de abertura e triagem de chamados de TI com classificação automática por IA
(zero-shot) e cálculo de urgência/SLA por categoria e setor. Backend em SQLite (via
Turso, banco remoto compatível com libSQL).

## Rodando localmente

```bash
pip install -r requirements.txt
pip install torch --index-url https://download.pytorch.org/whl/cpu "optimum[onnxruntime]"  # só pra converter o modelo (build-time)
python converter_modelo.py  # gera ./modelo_onnx uma vez; produção não precisa de torch/optimum, só onnxruntime
streamlit run app.py
```
