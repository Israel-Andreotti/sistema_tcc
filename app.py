import altair as alt
import pandas as pd
import streamlit as st

import backend_engine
import ia_classificador

st.set_page_config(page_title="Sistema de Tickets de TI", layout="wide")

# Gate simples de protótipo — não é autenticação real, só separa a navegação
# entre usuário comum e técnico de TI.
SENHA_TECNICO = "tecnico123"

# Paleta de status (fixa, nunca usada para outra coisa) — Baixa/Média/Alta/Crítica
CORES_URGENCIA = {
    "Baixa": "#0ca30c",
    "Média": "#fab219",
    "Alta": "#ec835a",
    "Crítica": "#d03b3b",
}
ORDEM_URGENCIA = ["Baixa", "Média", "Alta", "Crítica"]
ICONE_URGENCIA = {"Baixa": "🟢", "Média": "🟡", "Alta": "🟠", "Crítica": "🔴"}

# Paleta categórica fixa (slots 1-6 da paleta de referência), uma cor por categoria
CORES_CATEGORIA = ["#2a78d6", "#1baf7a", "#eda100", "#008300", "#4a3aa7", "#e34948"]


@st.cache_resource(show_spinner="Carregando modelo de IA (zero-shot)... isso só acontece uma vez.")
def carregar_modelo_ia():
    return ia_classificador.carregar_modelo()


def badge_urgencia(urgencia: str) -> str:
    cor = CORES_URGENCIA.get(urgencia, "#898781")
    return f'<span style="background-color:{cor}; color:white; padding:2px 8px; border-radius:4px; font-weight:600;">{urgencia}</span>'


def titulo_ticket(ticket: dict) -> str:
    icone = ICONE_URGENCIA.get(ticket["urgencia_calculada"], "⚪")
    tecnico_label = ticket["tecnico_atribuido"] or "não atribuído"
    return (f"{icone} {ticket['solicitante_nome']} · {ticket['categoria']} · {ticket['setor']} "
            f"· {ticket['status']} · Téc.: {tecnico_label}")


def renderizar_info_ticket(ticket: dict):
    col_info1, col_info2 = st.columns(2)
    with col_info1:
        st.markdown(f"**Ticket:** `{ticket['id']}`")
        st.markdown(f"**Solicitante:** {ticket['solicitante_nome']}")
        st.markdown(f"**Ramal:** {ticket['solicitante_ramal'] or '-'}")
        st.markdown(f"**Sala:** {ticket['solicitante_sala'] or '-'}")
        st.markdown(f"**Setor:** {ticket['setor']}")
    with col_info2:
        st.markdown(f"**Categoria (IA):** {ticket['categoria']} ({ticket['confianca_ia']:.0%} confiança)")
        st.markdown(f"**Urgência:** {badge_urgencia(ticket['urgencia_calculada'])} (score {ticket['urgencia_score']})",
                    unsafe_allow_html=True)
        st.markdown(f"**Criado em:** {ticket['data_criacao']}")
        st.markdown(f"**Prazo SLA:** {ticket['data_limite_sla']}")
    st.markdown(f"**Descrição original:** {ticket['descricao_original']}")


def renderizar_notas(ticket_id: str):
    notas = backend_engine.listar_notas(ticket_id)
    if not notas:
        st.caption("Nenhuma nota registrada ainda.")
    else:
        for nota in notas:
            st.markdown(f"- `{nota['data_hora']}` **{nota['tecnico_nome']}**: {nota['texto']}")


def _salvar_nota_e_limpar_campo(ticket_id: str, tecnico_key: str, texto_key: str):
    texto = st.session_state.get(texto_key, "").strip()
    tecnico_nome = st.session_state.get(tecnico_key)
    if not texto:
        return
    if backend_engine.adicionar_nota(ticket_id, tecnico_nome, texto):
        st.session_state[texto_key] = ""
        st.toast("Nota adicionada.")
    else:
        st.toast("Não foi possível adicionar a nota.", icon="⚠️")


def _abrir_ticket_e_limpar_formulario(opcoes_setor: dict):
    nome = st.session_state.get("abrir_nome", "").strip()
    ramal = st.session_state.get("abrir_ramal", "").strip()
    sala = st.session_state.get("abrir_sala", "").strip()
    descricao = st.session_state.get("abrir_descricao", "").strip()
    setor_nome = st.session_state.get("abrir_setor")

    if not nome or not descricao or setor_nome not in opcoes_setor:
        return

    with st.spinner("Classificando com IA e calculando urgência..."):
        resultado = backend_engine.criar_ticket(nome, ramal, sala, opcoes_setor[setor_nome], descricao)

    st.session_state["abrir_ticket_tem_resultado"] = True
    st.session_state["abrir_ticket_resultado"] = resultado

    st.session_state["abrir_nome"] = ""
    st.session_state["abrir_ramal"] = ""
    st.session_state["abrir_sala"] = ""
    st.session_state["abrir_descricao"] = ""
    st.session_state["abrir_setor"] = list(opcoes_setor.keys())[0]


def tela_abrir_ticket():
    carregar_modelo_ia()  # garante o modelo carregado antes do primeiro ticket

    setores = backend_engine.listar_setores()
    if not setores:
        st.warning("Nenhum setor cadastrado. Rode database/init_db.py para popular o banco.")
        return

    opcoes_setor = {s["nome"]: s["id"] for s in setores}

    st.text_input("Seu nome", key="abrir_nome")
    col_ramal, col_setor, col_sala = st.columns(3)
    col_ramal.text_input("Ramal", key="abrir_ramal")
    col_setor.selectbox("Setor", list(opcoes_setor.keys()), key="abrir_setor")
    col_sala.text_input("Sala", key="abrir_sala")
    st.text_area(
        "Descreva o problema", height=120,
        placeholder="Ex: O sistema PEP travou e não consigo acessar o prontuário do paciente...",
        key="abrir_descricao",
    )

    pode_enviar = bool(st.session_state.get("abrir_nome", "").strip()) and bool(st.session_state.get("abrir_descricao", "").strip())
    st.button(
        "Abrir chamado", type="primary", disabled=not pode_enviar,
        on_click=_abrir_ticket_e_limpar_formulario, args=(opcoes_setor,),
    )

    if st.session_state.get("abrir_ticket_tem_resultado"):
        resultado = st.session_state.get("abrir_ticket_resultado")
        if resultado is None:
            st.error("Não foi possível abrir o ticket. Verifique os dados e tente novamente.")
        else:
            st.success(f"Ticket {resultado['ticket_id']} criado com sucesso!")
            col1, col2, col3 = st.columns(3)
            col1.metric("Categoria (IA)", resultado["categoria_ia"])
            col2.markdown(f"**Urgência**<br>{badge_urgencia(resultado['urgencia'])}", unsafe_allow_html=True)
            col3.metric("SLA", f"{resultado['tempo_sla_minutos']} min")
            st.caption(f"Prazo limite: {resultado['data_limite']}")


def tela_painel():
    status_para_atualizar = [s for s in backend_engine.listar_status() if s != backend_engine.STATUS_CONCLUIDO]
    status_para_filtro = [s for s in status_para_atualizar if s != backend_engine.STATUS_CANCELADO]
    tecnicos = backend_engine.listar_tecnicos()
    opcoes_tecnico = {t["nome"]: t["id"] for t in tecnicos}

    filtro = st.multiselect("Filtrar por status", status_para_filtro, default=status_para_filtro)

    tickets = backend_engine.listar_tickets_ativos()
    tickets = [t for t in tickets if not filtro or t["status"] in filtro]

    if not tickets:
        st.info("Nenhum ticket ativo encontrado.")
        return

    st.write(f"{len(tickets)} ticket(s) encontrado(s) — clique em um ticket para ver detalhes e agir sobre ele.")

    for ticket in tickets:
        with st.expander(titulo_ticket(ticket)):
            renderizar_info_ticket(ticket)

            st.divider()
            col_atribuir, col_status = st.columns(2)

            with col_atribuir:
                st.markdown("**Atribuir técnico**")
                if not opcoes_tecnico:
                    st.warning("Nenhum técnico cadastrado.")
                else:
                    tecnico_escolhido = st.selectbox(
                        "Técnico", list(opcoes_tecnico.keys()), key=f"tecnico_{ticket['id']}"
                    )
                    if st.button("Atribuir", key=f"btn_atribuir_{ticket['id']}"):
                        if backend_engine.atribuir_tecnico(ticket["id"], opcoes_tecnico[tecnico_escolhido]):
                            st.success("Técnico atribuído. Status alterado automaticamente para 'Em Atendimento'.")
                            st.rerun()
                        else:
                            st.error("Não foi possível atribuir o técnico.")

            with col_status:
                st.markdown("**Atualizar status**")
                novo_status = st.selectbox("Novo status", status_para_atualizar, key=f"status_{ticket['id']}")
                if st.button("Atualizar", key=f"btn_status_{ticket['id']}"):
                    if backend_engine.atualizar_status(ticket["id"], novo_status):
                        st.success("Status atualizado.")
                        st.rerun()
                    else:
                        st.error("Não foi possível atualizar o status.")

            st.divider()
            st.markdown("**Concluir ticket**")
            confirmar_key = f"confirmar_conclusao_{ticket['id']}"
            if not st.session_state.get(confirmar_key, False):
                if st.button("Concluir Ticket", key=f"btn_concluir_{ticket['id']}"):
                    st.session_state[confirmar_key] = True
                    st.rerun()
            else:
                st.warning("Tem certeza que deseja concluir este ticket? Ele sairá da lista de tickets ativos e irá para o Histórico.")
                col_sim, col_nao = st.columns(2)
                if col_sim.button("Sim, concluir", key=f"btn_confirma_sim_{ticket['id']}", type="primary"):
                    if backend_engine.concluir_ticket(ticket["id"]):
                        st.session_state[confirmar_key] = False
                        st.success("Ticket concluído e movido para o Histórico.")
                        st.rerun()
                    else:
                        st.error("Não foi possível concluir o ticket.")
                if col_nao.button("Cancelar", key=f"btn_confirma_nao_{ticket['id']}"):
                    st.session_state[confirmar_key] = False
                    st.rerun()

            st.divider()
            st.markdown("**Notas de atendimento (procedimentos adotados)**")
            renderizar_notas(ticket["id"])

            if not opcoes_tecnico:
                st.warning("Cadastre um técnico para poder registrar notas.")
            else:
                col_nota_tec, col_nota_texto = st.columns([1, 3])
                tecnico_key = f"nota_tec_{ticket['id']}"
                texto_key = f"nota_texto_{ticket['id']}"
                col_nota_tec.selectbox("Técnico responsável", list(opcoes_tecnico.keys()), key=tecnico_key)
                texto_nota = col_nota_texto.text_area("Nova nota", key=texto_key, height=80)
                st.button(
                    "Adicionar nota", key=f"btn_nota_{ticket['id']}", disabled=not texto_nota.strip(),
                    on_click=_salvar_nota_e_limpar_campo, args=(ticket["id"], tecnico_key, texto_key),
                )


def tela_historico():
    tickets = backend_engine.listar_tickets_historico()

    if not tickets:
        st.info("Nenhum ticket concluído ainda.")
        return

    st.write(f"{len(tickets)} ticket(s) concluído(s)")

    for ticket in tickets:
        with st.expander(titulo_ticket(ticket)):
            renderizar_info_ticket(ticket)
            st.divider()
            st.markdown("**Notas de atendimento (procedimentos adotados)**")
            renderizar_notas(ticket["id"])


def tela_dashboard():
    tickets = backend_engine.listar_tickets()
    df = pd.DataFrame(tickets)

    if df.empty:
        st.info("Sem dados suficientes para o dashboard ainda.")
        return

    col_a, col_b = st.columns(2)

    with col_a:
        st.subheader("Tickets por urgência")
        contagem_urg = df["urgencia_calculada"].value_counts().reindex(ORDEM_URGENCIA, fill_value=0).reset_index()
        contagem_urg.columns = ["urgencia", "quantidade"]
        grafico_urg = alt.Chart(contagem_urg).mark_bar().encode(
            x=alt.X("urgencia:N", sort=ORDEM_URGENCIA, title=None),
            y=alt.Y("quantidade:Q", title="Tickets"),
            color=alt.Color("urgencia:N", scale=alt.Scale(domain=ORDEM_URGENCIA, range=[CORES_URGENCIA[u] for u in ORDEM_URGENCIA]), legend=None),
            tooltip=["urgencia", "quantidade"],
        )
        st.altair_chart(grafico_urg, width='stretch')

    with col_b:
        st.subheader("Tickets por setor")
        contagem_setor = df["setor"].value_counts().reset_index()
        contagem_setor.columns = ["setor", "quantidade"]
        grafico_setor = alt.Chart(contagem_setor).mark_bar().encode(
            x=alt.X("quantidade:Q", title="Tickets"),
            y=alt.Y("setor:N", sort="-x", title=None),
            tooltip=["setor", "quantidade"],
        )
        st.altair_chart(grafico_setor, width='stretch')

    st.subheader("Tickets por categoria (classificação da IA)")
    categorias_ordenadas = sorted(df["categoria"].unique().tolist())
    contagem_cat = df["categoria"].value_counts().reindex(categorias_ordenadas, fill_value=0).reset_index()
    contagem_cat.columns = ["categoria", "quantidade"]
    grafico_cat = alt.Chart(contagem_cat).mark_bar().encode(
        x=alt.X("categoria:N", sort=categorias_ordenadas, title=None),
        y=alt.Y("quantidade:Q", title="Tickets"),
        color=alt.Color("categoria:N", scale=alt.Scale(domain=categorias_ordenadas, range=CORES_CATEGORIA[:len(categorias_ordenadas)]), legend=None),
        tooltip=["categoria", "quantidade"],
    )
    st.altair_chart(grafico_cat, width='stretch')


st.title("Sistema de Tickets de TI")

papel = st.sidebar.radio("Acessar como", ["Usuário Comum", "Técnico de TI"])

if papel == "Usuário Comum":
    st.header("Abrir Ticket")
    tela_abrir_ticket()
else:
    senha = st.sidebar.text_input("Senha de técnico", type="password")
    if not senha:
        st.info("Digite a senha de técnico na barra lateral para acessar o painel.")
    elif senha != SENHA_TECNICO:
        st.error("Senha incorreta.")
    else:
        tab_abrir, tab_painel, tab_historico, tab_dashboard = st.tabs(
            ["Abrir Ticket", "Painel de Tickets", "Histórico", "Dashboard"]
        )
        with tab_abrir:
            tela_abrir_ticket()
        with tab_painel:
            tela_painel()
        with tab_historico:
            tela_historico()
        with tab_dashboard:
            tela_dashboard()
