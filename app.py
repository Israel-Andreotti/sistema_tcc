import datetime
import os

import altair as alt
import pandas as pd
import streamlit as st

import backend_engine
import ia_classificador
import urgencia_engine

# Credenciais do Turso ficam em .streamlit/secrets.toml (local) ou no painel de
# Secrets do Streamlit Cloud (produção); espelhadas pra variável de ambiente
# porque é isso que backend_engine.py lê.
try:
    for _chave in ("TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN"):
        if _chave not in os.environ and _chave in st.secrets:
            os.environ[_chave] = st.secrets[_chave]
except Exception:
    pass

# Gate simples de protótipo — não é autenticação real, só separa a navegação
# entre usuário comum e técnico de TI.
SENHA_TECNICO = "tecnico123"

# Session state dos widgets de login persiste entre reruns antes mesmo desses
# widgets serem recriados — dá pra usar isso pra recolher a sidebar assim que
# o técnico loga, sem esperar mais uma interação.
_JA_AUTENTICADO = (
    st.session_state.get("papel_selecionado") == "Técnico de TI"
    and st.session_state.get("senha_tecnico") == SENHA_TECNICO
)

st.set_page_config(
    page_title="Sistema de Tickets de TI",
    layout="wide",
    initial_sidebar_state="collapsed" if _JA_AUTENTICADO else "expanded",
)

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

# Paleta de criticidade de setor (1 = menos crítico ... 5 = mais crítico)
CORES_CRITICIDADE = {
    1: "#0ca30c",
    2: "#2a78d6",
    3: "#eda100",
    4: "#ec835a",
    5: "#d03b3b",
}

PLACEHOLDER_TECNICO = "— selecione —"

# Sugestão de SLA (minutos) por categoria, de acordo com a criticidade escolhida para
# um setor novo — mesmos padrões usados nos setores originais em database/seed.sql.
# categoria_id: 1=Sistemas, 2=Rede, 3=Hardware, 4=Contas e Senhas, 5=Telefonia, 6=Impressoras
TIER_SLA_PADRAO = {
    5: {1: 30, 2: 45, 3: 45, 4: 60, 5: 90, 6: 180},
    4: {1: 60, 2: 90, 3: 90, 4: 180, 5: 240, 6: 60},
    3: {1: 120, 2: 180, 3: 120, 4: 180, 5: 240, 6: 60},
    2: {1: 240, 2: 480, 3: 360, 4: 480, 5: 720, 6: 720},
    1: {1: 240, 2: 480, 3: 360, 4: 480, 5: 720, 6: 720},
}


@st.cache_resource(show_spinner="Carregando modelo de IA (zero-shot)... isso só acontece uma vez.")
def carregar_modelo_ia():
    return ia_classificador.carregar_modelo()


def badge_urgencia(urgencia: str) -> str:
    cor = CORES_URGENCIA.get(urgencia, "#898781")
    return f'<span style="background-color:{cor}; color:white; padding:2px 8px; border-radius:4px; font-weight:600;">{urgencia}</span>'


def badge_criticidade(nivel: int) -> str:
    cor = CORES_CRITICIDADE.get(nivel, "#898781")
    return f'<span style="background-color:{cor}; color:white; padding:2px 8px; border-radius:4px; font-weight:600;">{nivel}</span>'


def formatar_sla(minutos: int) -> str:
    if minutos < 60:
        return f"{minutos} min"
    horas, resto = divmod(minutos, 60)
    return f"{horas}h" if resto == 0 else f"{horas}h{resto}min"


def titulo_ticket(ticket: dict) -> str:
    icone = ICONE_URGENCIA.get(ticket["urgencia_calculada"], "⚪")
    tecnico_label = ticket["tecnico_atribuido"] or "não atribuído"
    return (f"{icone} #{ticket['numero']} · {ticket['solicitante_nome']} · {ticket['categoria']} · {ticket['setor']} "
            f"· {ticket['status']} · Téc.: {tecnico_label}")


def renderizar_info_ticket(ticket: dict):
    col_info1, col_info2 = st.columns(2)
    with col_info1:
        st.markdown(f"**Ticket:** #{ticket['numero']}")
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


def _atribuir_tecnico_e_limpar(ticket_id: str, opcoes_tecnico: dict, tecnico_key: str):
    tecnico_escolhido = st.session_state.get(tecnico_key)
    if tecnico_escolhido not in opcoes_tecnico:
        return
    if backend_engine.atribuir_tecnico(ticket_id, opcoes_tecnico[tecnico_escolhido]):
        st.toast("Técnico atribuído. Status alterado automaticamente para 'Em Atendimento'.")
    else:
        st.toast("Não foi possível atribuir o técnico.", icon="⚠️")


def _sanitizar_ramal():
    valor_digitado = st.session_state.get("abrir_ramal", "")
    st.session_state["ramal_tem_letra"] = any(not c.isdigit() for c in valor_digitado)
    st.session_state["abrir_ramal"] = "".join(c for c in valor_digitado if c.isdigit())


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
    st.session_state["ramal_tem_letra"] = False
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
    col_ramal.text_input("Ramal", key="abrir_ramal", on_change=_sanitizar_ramal)
    if st.session_state.get("ramal_tem_letra"):
        col_ramal.markdown(":red[Só é permitido digitar números no campo Ramal.]")
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
            st.success(f"Ticket #{resultado['numero']} criado com sucesso! Guarde esse número para consultar depois.")
            col1, col2, col3 = st.columns(3)
            col1.metric("Categoria (IA)", resultado["categoria_ia"])
            col2.markdown(f"**Urgência**<br>{badge_urgencia(resultado['urgencia'])}", unsafe_allow_html=True)
            col3.metric("Tempo médio de resolução", formatar_sla(resultado["tempo_sla_minutos"]))
            st.caption(f"Prazo limite: {resultado['data_limite']}")


@st.fragment(run_every="15s")
def tela_painel():
    status_para_filtro = [
        s for s in backend_engine.listar_status()
        if s not in (backend_engine.STATUS_CONCLUIDO, backend_engine.STATUS_CANCELADO)
    ]
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
            col_atribuir, col_cancelar = st.columns(2)

            with col_atribuir:
                st.markdown("**Atribuir técnico**")
                if not opcoes_tecnico:
                    st.warning("Nenhum técnico cadastrado.")
                else:
                    tecnico_atual = ticket["tecnico_atribuido"]
                    # A chave inclui o técnico atual para forçar o Streamlit a recriar o
                    # widget (e reaplicar o índice) sempre que a atribuição mudar — se a
                    # chave fosse fixa, o valor salvo em session_state teria prioridade
                    # sobre o índice em reruns futuros.
                    tecnico_key = f"tecnico_{ticket['id']}_{tecnico_atual or 'none'}"
                    opcoes_lista = [PLACEHOLDER_TECNICO] + list(opcoes_tecnico.keys())
                    index_atual = opcoes_lista.index(tecnico_atual) if tecnico_atual in opcoes_lista else 0
                    tecnico_escolhido = st.selectbox(
                        "Técnico", opcoes_lista, index=index_atual, key=tecnico_key
                    )
                    st.button(
                        "Atribuir", key=f"btn_atribuir_{ticket['id']}", disabled=tecnico_escolhido == PLACEHOLDER_TECNICO,
                        on_click=_atribuir_tecnico_e_limpar, args=(ticket["id"], opcoes_tecnico, tecnico_key),
                    )

            with col_cancelar:
                st.markdown("**Cancelar ticket**")
                confirmar_cancelamento_key = f"confirmar_cancelamento_{ticket['id']}"
                if not st.session_state.get(confirmar_cancelamento_key, False):
                    if st.button("Cancelar Ticket", key=f"btn_cancelar_{ticket['id']}"):
                        st.session_state[confirmar_cancelamento_key] = True
                        st.rerun()
                else:
                    st.warning("Tem certeza que deseja cancelar este ticket? Ele sairá da lista de tickets ativos e irá para o Histórico.")
                    col_sim_c, col_nao_c = st.columns(2)
                    if col_sim_c.button("Sim, cancelar", key=f"btn_confirma_cancelar_sim_{ticket['id']}", type="primary"):
                        if backend_engine.cancelar_ticket(ticket["id"]):
                            st.session_state[confirmar_cancelamento_key] = False
                            st.success("Ticket cancelado e movido para o Histórico.")
                            st.rerun()
                        else:
                            st.error("Não foi possível cancelar o ticket.")
                    if col_nao_c.button("Voltar", key=f"btn_confirma_cancelar_nao_{ticket['id']}"):
                        st.session_state[confirmar_cancelamento_key] = False
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

            st.divider()
            btn_concluir_key = f"btn_concluir_{ticket['id']}"
            st.markdown(
                f"""
                <style>
                div.st-key-{btn_concluir_key} button {{
                    background-color:#0ca30c;
                    color:white;
                    border:none;
                }}
                div.st-key-{btn_concluir_key} button:hover {{
                    background-color:#098a09;
                    color:white;
                    border:none;
                }}
                </style>
                """,
                unsafe_allow_html=True,
            )
            confirmar_key = f"confirmar_conclusao_{ticket['id']}"
            if not st.session_state.get(confirmar_key, False):
                _, col_meio, _ = st.columns([2, 1, 2])
                with col_meio:
                    if st.button("Concluir Ticket", key=btn_concluir_key, use_container_width=True):
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
                if col_nao.button("Voltar", key=f"btn_confirma_nao_{ticket['id']}"):
                    st.session_state[confirmar_key] = False
                    st.rerun()


def tela_historico():
    tickets = backend_engine.listar_tickets_historico()

    if not tickets:
        st.info("Nenhum ticket concluído ainda.")
        return

    setores_disponiveis = sorted({t["setor"] for t in tickets})
    situacoes_disponiveis = sorted({t["status"] for t in tickets})

    col_num, col_setor, col_situacao = st.columns(3)
    busca_numero = col_num.text_input("Número do ticket", placeholder="Ex: 12")
    setores_filtro = col_setor.multiselect("Setor", setores_disponiveis, placeholder="Selecione uma ou mais opções")
    situacoes_filtro = col_situacao.multiselect("Situação", situacoes_disponiveis, placeholder="Selecione uma ou mais opções")

    col_data_ini, col_data_fim = st.columns(2)
    data_inicial = col_data_ini.date_input("Data inicial", value=None, format="DD/MM/YYYY")
    data_final = col_data_fim.date_input("Data final", value=None, format="DD/MM/YYYY")

    if busca_numero.strip():
        tickets = [t for t in tickets if busca_numero.strip() in str(t["numero"])]
    if setores_filtro:
        tickets = [t for t in tickets if t["setor"] in setores_filtro]
    if situacoes_filtro:
        tickets = [t for t in tickets if t["status"] in situacoes_filtro]
    if data_inicial:
        tickets = [
            t for t in tickets
            if datetime.datetime.strptime(t["data_criacao"], "%Y-%m-%d %H:%M:%S").date() >= data_inicial
        ]
    if data_final:
        tickets = [
            t for t in tickets
            if datetime.datetime.strptime(t["data_criacao"], "%Y-%m-%d %H:%M:%S").date() <= data_final
        ]

    if not tickets:
        st.info("Nenhum ticket encontrado com os filtros selecionados.")
        return

    st.write(f"{len(tickets)} ticket(s) encontrado(s)")

    for ticket in tickets:
        with st.expander(titulo_ticket(ticket)):
            renderizar_info_ticket(ticket)
            st.divider()
            st.markdown("**Notas de atendimento (procedimentos adotados)**")
            renderizar_notas(ticket["id"])


def _cadastrar_setor_e_limpar():
    nome = st.session_state.get("novo_setor_nome", "").strip()
    sigla = st.session_state.get("novo_setor_sigla", "").strip()
    criticidade = st.session_state.get("novo_setor_criticidade")

    novo_id = backend_engine.criar_setor(nome, sigla.upper(), criticidade)
    if novo_id is None:
        st.toast("Não foi possível cadastrar o setor. Verifique se o nome ou a sigla já existem.", icon="⚠️")
        return

    st.session_state["setor_pendente_sla"] = {"id": novo_id, "nome": nome, "criticidade_peso": criticidade}
    st.session_state["novo_setor_nome"] = ""
    st.session_state["novo_setor_sigla"] = ""


def tela_gerenciar_setores():
    st.subheader("Cadastrar novo setor")

    setor_pendente = st.session_state.get("setor_pendente_sla")

    if not setor_pendente:
        nome = st.text_input("Nome do setor", key="novo_setor_nome")
        sigla = st.text_input("Sigla (única)", key="novo_setor_sigla", placeholder="Ex: RH")
        st.selectbox(
            "Criticidade (1 = menos crítico, 5 = mais crítico)", [1, 2, 3, 4, 5], index=2,
            key="novo_setor_criticidade",
        )

        pode_cadastrar = bool(nome.strip()) and bool(sigla.strip())
        st.button(
            "Cadastrar setor", type="primary", disabled=not pode_cadastrar,
            on_click=_cadastrar_setor_e_limpar,
        )
    else:
        st.success(f"Setor **{setor_pendente['nome']}** cadastrado! Agora defina o SLA (em minutos) para cada categoria.")
        categorias = backend_engine.listar_categorias()
        tier = TIER_SLA_PADRAO.get(setor_pendente["criticidade_peso"], TIER_SLA_PADRAO[2])

        valores_sla = {}
        for categoria in categorias:
            valor_padrao = tier.get(categoria["id"], 240)
            valores_sla[categoria["id"]] = st.number_input(
                categoria["nome"], min_value=5, max_value=2880, step=5, value=valor_padrao,
                key=f"sla_novo_{setor_pendente['id']}_{categoria['id']}",
            )

        col_salvar, col_pular = st.columns(2)
        if col_salvar.button("Salvar SLA e concluir", type="primary"):
            for categoria_id, minutos in valores_sla.items():
                backend_engine.definir_sla(categoria_id, setor_pendente["id"], int(minutos))
            st.session_state.pop("setor_pendente_sla", None)
            st.success("SLA salvo com sucesso!")
            st.rerun()
        if col_pular.button("Pular por agora"):
            st.session_state.pop("setor_pendente_sla", None)
            st.info("Setor cadastrado sem SLA específico — vai usar o padrão genérico até você configurar.")
            st.rerun()

    st.divider()
    st.subheader("Setores cadastrados")

    setores = backend_engine.listar_setores()
    if not setores:
        st.info("Nenhum setor cadastrado ainda.")
        return

    busca_setor = st.text_input(
        "Pesquisar setor", placeholder="Digite o nome ou a sigla do setor...", key="busca_setor",
    )
    if busca_setor.strip():
        termo_busca = busca_setor.strip().lower()
        setores_filtrados = [
            s for s in setores if termo_busca in s["nome"].lower() or termo_busca in s["sigla"].lower()
        ]
    else:
        setores_filtrados = setores

    if not setores_filtrados:
        st.info("Nenhum setor encontrado para essa busca.")
        return

    categorias = backend_engine.listar_categorias()

    st.markdown(
        """
        <style>
        div[class*="st-key-setor_linha_"] {
            padding: 8px 4px;
            border-radius: 6px;
        }
        div[class*="st-key-setor_linha_"]:hover {
            background-color: rgba(127, 127, 127, 0.12);
        }
        div[class*="st-key-setor_edit_btn_"] button {
            opacity: 0;
            transition: opacity 0.15s ease;
            padding: 0.1rem 0.5rem;
            min-height: 0;
        }
        div[class*="st-key-setor_linha_"]:hover div[class*="st-key-setor_edit_btn_"] button {
            opacity: 1;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    col_h1, col_h2, col_h3, _ = st.columns([3, 1, 5, 1])
    col_h1.markdown("**Setor**")
    col_h2.markdown("**Criticidade**")
    col_h3.markdown("**SLA por categoria**")

    for setor in setores_filtrados:
        setor_id = setor["id"]
        editando_key = f"editando_setor_{setor_id}"
        sla_atual = backend_engine.obter_sla_setor(setor_id)

        with st.container(key=f"setor_linha_{setor_id}"):
            if not st.session_state.get(editando_key, False):
                col1, col2, col3, col4 = st.columns([3, 1, 5, 1])
                col1.write(f"{setor['nome']} ({setor['sigla']})")
                col2.markdown(badge_criticidade(setor["criticidade_peso"]), unsafe_allow_html=True)
                resumo_sla = " · ".join(
                    f"{c['nome']}: {formatar_sla(sla_atual.get(c['id'], urgencia_engine.SLA_PADRAO_MINUTOS))}"
                    for c in categorias
                )
                col3.write(resumo_sla)
                with col4:
                    if st.button("✏️", key=f"setor_edit_btn_{setor_id}"):
                        st.session_state[editando_key] = True
                        st.rerun()
            else:
                st.markdown(f"**Editando: {setor['nome']}**")
                novo_nome = st.text_input("Nome", value=setor["nome"], key=f"editar_nome_{setor_id}")
                nova_sigla = st.text_input("Sigla", value=setor["sigla"], key=f"editar_sigla_{setor_id}")
                nova_criticidade = st.selectbox(
                    "Criticidade", [1, 2, 3, 4, 5], index=setor["criticidade_peso"] - 1,
                    key=f"editar_criticidade_{setor_id}",
                )

                st.caption("SLA por categoria (minutos)")
                novos_sla = {}
                cols_sla = st.columns(len(categorias))
                for col, categoria in zip(cols_sla, categorias):
                    valor_atual = sla_atual.get(categoria["id"], urgencia_engine.SLA_PADRAO_MINUTOS)
                    novos_sla[categoria["id"]] = col.number_input(
                        categoria["nome"], min_value=5, max_value=2880, step=5, value=valor_atual,
                        key=f"editar_sla_{setor_id}_{categoria['id']}",
                    )

                col_salvar, col_cancelar = st.columns(2)
                if col_salvar.button("Salvar", key=f"btn_salvar_setor_{setor_id}", type="primary"):
                    if backend_engine.atualizar_setor(setor_id, novo_nome.strip(), nova_sigla.strip().upper(), nova_criticidade):
                        for categoria_id, minutos in novos_sla.items():
                            backend_engine.definir_sla(categoria_id, setor_id, int(minutos))
                        st.session_state[editando_key] = False
                        st.success("Setor atualizado. Os novos tickets já vão usar os valores atualizados.")
                        st.rerun()
                    else:
                        st.error("Não foi possível atualizar. O nome ou a sigla podem já estar em uso.")
                if col_cancelar.button("Cancelar", key=f"btn_cancelar_setor_{setor_id}"):
                    st.session_state[editando_key] = False
                    st.rerun()

                confirmar_exclusao_key = f"confirmar_exclusao_setor_{setor_id}"
                if not st.session_state.get(confirmar_exclusao_key, False):
                    if st.button("Excluir setor", key=f"btn_excluir_setor_{setor_id}"):
                        st.session_state[confirmar_exclusao_key] = True
                        st.rerun()
                else:
                    st.warning(f"Tem certeza que deseja excluir **{setor['nome']}**? Essa ação não pode ser desfeita.")
                    col_sim, col_nao = st.columns(2)
                    if col_sim.button("Sim, excluir", key=f"btn_confirma_excluir_sim_{setor_id}", type="primary"):
                        sucesso, mensagem = backend_engine.excluir_setor(setor_id)
                        st.session_state[confirmar_exclusao_key] = False
                        if sucesso:
                            st.session_state[editando_key] = False
                            st.success(mensagem)
                        else:
                            st.error(mensagem)
                        st.rerun()
                    if col_nao.button("Voltar", key=f"btn_confirma_excluir_nao_{setor_id}"):
                        st.session_state[confirmar_exclusao_key] = False
                        st.rerun()

        st.divider()


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

papel = st.sidebar.radio("Acessar como", ["Usuário Comum", "Técnico de TI"], key="papel_selecionado")

if papel == "Usuário Comum":
    st.header("Abrir Ticket")
    tela_abrir_ticket()
else:
    senha = st.sidebar.text_input("Senha de técnico", type="password", key="senha_tecnico")
    st.sidebar.button("Entrar")
    if not senha:
        st.info("Digite a senha de técnico na barra lateral para acessar o painel.")
    elif senha != SENHA_TECNICO:
        st.error("Senha incorreta.")
    else:
        tab_abrir, tab_painel, tab_historico, tab_setores, tab_dashboard = st.tabs(
            ["Abrir Ticket", "Painel de Tickets", "Histórico", "Gerenciar Setores", "Dashboard"]
        )
        with tab_abrir:
            tela_abrir_ticket()
        with tab_painel:
            tela_painel()
        with tab_historico:
            tela_historico()
        with tab_setores:
            tela_gerenciar_setores()
        with tab_dashboard:
            tela_dashboard()
