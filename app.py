"""
app.py
======
INTERFACE WEB da aplicação (Streamlit).

Oferece no navegador o mesmo fluxo do main.py (captura -> cálculo ->
relatórios), com formulário na barra lateral, gráficos interativos e
botões para baixar os relatórios HTML e Excel.

Execução:
    streamlit run app.py

Os módulos captura.py, indicadores.py e relatorio.py são reaproveitados sem
alteração: esta interface apenas chama as mesmas funções que o main.py usa.
"""

import tempfile
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import captura
import indicadores
import relatorio
from main import ANOS_PADRAO, ARQUIVO_EXEMPLO, ULTIMO_ANO

# ---------------------------------------------------------------------------
# Configuração geral
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Análise de Demonstrações Financeiras", page_icon="📊", layout="wide")

# Paleta categórica (ordem fixa, validada para daltonismo). Cada série recebe
# sempre a mesma cor, na ordem em que aparece; nunca se reaproveita cor por posição.
CORES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]

# Primeiro ano com DFP disponível nos dados abertos da CVM
PRIMEIRO_ANO_CVM = 2010

# Nível do diagnóstico -> (caixa colorida do Streamlit, ícone). O ícone garante que o
# tipo de comentário não dependa só da cor (acessibilidade para daltônicos).
CAIXA_DIAGNOSTICO = {"ok": (st.success, "✅"), "atencao": (st.warning, "⚠️"),
                     "alerta": (st.error, "🚨"), "info": (st.info, "ℹ️")}


# ---------------------------------------------------------------------------
# Funções com cache (evitam repetir downloads e leituras a cada clique)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def buscar_empresas(termo, ano):
    """Busca companhias pelo nome na DFP da CVM (resultado guardado em cache)."""
    return captura.buscar_empresas(termo, ano)


@st.cache_data(show_spinner=False)
def capturar_cvm(cd_cvm, anos):
    """Captura as demonstrações de uma empresa na CVM (resultado guardado em cache)."""
    return captura.capturar_cvm(cd_cvm, list(anos))


@st.cache_data(show_spinner=False)
def capturar_mercado(ticker, valor_manual):
    """Obtém o valor de mercado via yfinance ou valor informado (em cache)."""
    return captura.capturar_mercado(ticker, valor_manual)


# ---------------------------------------------------------------------------
# Formulário (barra lateral)
# ---------------------------------------------------------------------------

def formulario():
    """
    Monta a barra lateral e devolve um dicionário com o pedido do usuário
    (fonte e parâmetros), ou None enquanto o botão "Analisar" não for clicado.
    """
    st.sidebar.title("📊 Análise financeira")
    st.sidebar.caption("TP1 · Administração Financeira (CAD 167) · UFMG")

    fonte = st.sidebar.radio("Fonte dos dados", ["CVM (empresas brasileiras)", "Arquivo CSV", "Empresa de exemplo"])
    pedido = {"ticker": None, "valor_mercado": None}

    if fonte.startswith("CVM"):
        pedido["fonte"] = "cvm"
        termo = st.sidebar.text_input("Nome (ou parte do nome) da empresa", "weg",
                                      help="Ex.: weg, ambev, natura, embraer. Bancos e seguradoras não são suportados.")
        anos = st.sidebar.multiselect("Exercícios", list(range(PRIMEIRO_ANO_CVM, ULTIMO_ANO + 1)), ANOS_PADRAO,
                                      help="Escolha ao menos dois anos para ter análise horizontal e DuPont.")
        if not termo.strip() or not anos:
            st.sidebar.info("Informe o nome da empresa e ao menos um exercício.")
            return None

        # A busca baixa a DFP do ano mais recente (só na primeira vez; depois usa o cache em disco)
        with st.spinner(f"Buscando '{termo}' na base da CVM (o primeiro download pode levar alguns minutos)..."):
            try:
                achadas = buscar_empresas(termo.strip(), max(anos))
            except Exception as erro:
                st.sidebar.error(f"Não foi possível acessar a CVM: {erro}")
                return None
        if achadas.empty:
            st.sidebar.warning("Nenhuma companhia encontrada. A CVM só tem companhias abertas brasileiras "
                               "(a Petrobras está como 'petroleo brasileiro').")
            return None

        # Lista as empresas encontradas para o usuário escolher a certa
        rotulos = [f"{l.DENOM_CIA} (CVM {int(l.CD_CVM)})" for l in achadas.itertuples()]
        escolha = st.sidebar.selectbox(f"Empresa ({len(achadas)} encontrada(s))", range(len(rotulos)),
                                       format_func=lambda i: rotulos[i])
        pedido["cd_cvm"] = int(achadas.at[escolha, "CD_CVM"])
        pedido["anos"] = tuple(sorted(anos))

        # Dados de mercado (opcionais) para os índices de avaliação
        with st.sidebar.expander("Dados de mercado (opcional)"):
            pedido["ticker"] = st.text_input("Ticker na B3", placeholder="ex.: WEGE3").strip() or None
            valor = st.number_input("ou valor de mercado (R$)", min_value=0.0, value=0.0, step=1e9, format="%.0f")
            pedido["valor_mercado"] = valor or None

    elif fonte == "Arquivo CSV":
        pedido["fonte"] = "csv"
        arquivo = st.sidebar.file_uploader("Arquivo CSV", type=["csv"],
                                           help="Use o formato de dados/modelo_empresa.csv (uma conta por linha, um ano por coluna).")
        st.sidebar.download_button("Baixar modelo em branco", (Path(__file__).parent / "dados" / "modelo_empresa.csv").read_bytes(),
                                   "modelo_empresa.csv", "text/csv")
        if arquivo is None:
            st.sidebar.info("Envie um arquivo CSV preenchido.")
            return None
        pedido["arquivo"] = arquivo
        pedido["nome"] = st.sidebar.text_input("Nome da empresa", Path(arquivo.name).stem.replace("_", " ").title())
        with st.sidebar.expander("Dados de mercado (opcional)"):
            valor = st.number_input("Valor de mercado (R$)", min_value=0.0, value=0.0, step=1e9, format="%.0f")
            pedido["valor_mercado"] = valor or None

    else:
        pedido["fonte"] = "exemplo"
        st.sidebar.caption("Dados fictícios, funcionam sem internet.")

    return pedido if st.sidebar.button("Analisar", type="primary", width="stretch") else None


def executar(pedido):
    """
    Etapas 1 e 2 da aplicação: captura os dados conforme o pedido e calcula
    indicadores e diagnóstico. Devolve um dicionário com tudo que a tela usa.
    """
    if pedido["fonte"] == "cvm":
        df, meta = capturar_cvm(pedido["cd_cvm"], pedido["anos"])
    elif pedido["fonte"] == "csv":
        # capturar_csv lê de um caminho: o arquivo enviado é gravado numa pasta temporária
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / pedido["arquivo"].name
            caminho.write_bytes(pedido["arquivo"].getvalue())
            df, meta = captura.capturar_csv(caminho, pedido["nome"])
    else:
        df, meta = captura.capturar_csv(ARQUIVO_EXEMPLO, "Empresa Exemplo S.A. (dados fictícios)")

    mercado = capturar_mercado(pedido["ticker"], pedido["valor_mercado"])
    ind = indicadores.calcular_indicadores(df, mercado)
    diag = indicadores.diagnostico(df, ind, mercado)
    return {"df": df, "meta": meta, "mercado": mercado, "ind": ind, "diag": diag}


# ---------------------------------------------------------------------------
# Gráficos (Plotly: interativos, mostram os valores ao passar o mouse)
# ---------------------------------------------------------------------------

def _layout(fig, titulo, sufixo=""):
    """Estilo comum: título, legenda abaixo do gráfico, números no padrão brasileiro."""
    fig.update_layout(
        title=dict(text=titulo, font=dict(size=15)),
        separators=",.",                      # vírgula decimal, ponto de milhar
        # legenda embaixo: com 3-4 séries ela quebra em duas linhas e cobriria o título se ficasse em cima
        legend=dict(orientation="h", yanchor="top", y=-0.12, x=0),
        margin=dict(l=10, r=10, t=50, b=10), height=380,
        barcornerradius=4, bargap=0.3, bargroupgap=0.08,
    )
    fig.update_xaxes(type="category", showgrid=False)
    fig.update_yaxes(ticksuffix=sufixo, zeroline=True)
    return fig


def grafico_linhas(ind, chaves, titulo, unidade, referencia=None):
    """Linhas de indicadores ao longo dos anos (margens, liquidez, prazos)."""
    anos = [str(a) for a in ind.columns]
    fator, sufixo, formato = {"%": (100, "%", ".1f"), "x": (1, "x", ".2f"), "dias": (1, "", ".0f")}[unidade]
    fig = go.Figure()
    for i, chave in enumerate(c for c in chaves if c in ind.index):
        fig.add_scatter(x=anos, y=ind.loc[chave] * fator, name=indicadores.POR_CHAVE[chave].nome,
                        mode="lines+markers", line=dict(width=2, color=CORES[i]), marker=dict(size=8),
                        hovertemplate=f"%{{y:{formato}}}{sufixo or ' dias'}<extra>%{{fullData.name}}</extra>")
    if referencia is not None:  # linha de referência (ex.: liquidez = 1)
        fig.add_hline(y=referencia, line=dict(dash="dash", width=1, color="#898781"))
    fig.update_layout(hovermode="x unified")
    return _layout(fig, titulo, sufixo)


def grafico_barras(df, contas, titulo, empilhado=False):
    """Barras agrupadas (ou empilhadas em %) de contas das demonstrações."""
    anos = [str(a) for a in df.columns]
    fig = go.Figure()
    for i, (nome, serie) in enumerate(contas):
        fig.add_bar(x=anos, y=serie, name=nome, marker=dict(color=CORES[i], line=dict(width=1, color="rgba(0,0,0,0)")),
                    hovertemplate=f"{nome}: %{{y:,.1f}}{'%' if empilhado else ' mi'}<extra></extra>")
    if empilhado:
        fig.update_layout(barmode="stack")
    return _layout(fig, titulo, "%" if empilhado else "")


def grafico_dupont(df):
    """Os três fatores do ROE (Eq. 2.18) lado a lado, um gráfico pequeno por fator."""
    dp = indicadores.dupont(df)
    anos = [str(a) for a in df.columns]
    fatores = [("margem_liquida", "Margem líquida", 100, "%"), ("giro_ativos", "× Giro dos ativos", 1, "x"),
               ("multiplicador_pl", "× Multiplicador do PL", 1, "x"), ("roe", "= ROE", 100, "%")]
    colunas = st.columns(4)
    for coluna, (chave, titulo, fator, sufixo) in zip(colunas, fatores):
        fig = go.Figure(go.Bar(x=anos, y=dp.loc[chave] * fator, marker_color=CORES[1] if chave == "roe" else CORES[0],
                               hovertemplate=f"%{{y:.2f}}{sufixo}<extra></extra>"))
        _layout(fig, titulo, sufixo).update_layout(height=260, showlegend=False)
        coluna.plotly_chart(fig, width="stretch")


# ---------------------------------------------------------------------------
# Tabelas
# ---------------------------------------------------------------------------

def tabelas_indicadores(ind):
    """Mostra os indicadores formatados (R$ mi, %, x, dias), com referência do Berk
    e fórmula, em uma tabela por categoria (liquidez, margens, ...)."""
    categorias = {}
    for chave in ind.index:
        meta = indicadores.POR_CHAVE[chave]
        linha = {"Indicador": meta.nome}
        linha.update({str(a): relatorio.formatar(v, meta.unidade) for a, v in ind.loc[chave].items()})
        linha.update({"Ref. (Berk)": meta.referencia, "Fórmula": meta.formula})
        categorias.setdefault(meta.categoria, []).append(linha)
    for categoria, linhas in categorias.items():
        st.markdown(f"**{categoria}**")
        st.dataframe(pd.DataFrame(linhas), hide_index=True, width="stretch",
                     column_config={"Indicador": st.column_config.TextColumn(width="large"),
                                    "Fórmula": st.column_config.TextColumn(width="large")})


def tabela_contas(tab, contas, formato):
    """Contas das demonstrações com descrição legível; `formato` converte cada valor em texto."""
    saida = tab.loc[[c for c in contas if c in tab.index]].copy()
    saida.index = [captura.DESCRICAO_CONTAS[c] for c in saida.index]
    saida.columns = [str(a) for a in saida.columns]
    return saida.apply(lambda col: col.map(formato))


def mostrar_tabela(tab, **opcoes):
    """Mostra a tabela com altura suficiente para todas as linhas, sem rolagem
    interna (o padrão do Streamlit corta em ~10 linhas). 35 px por linha + cabeçalho."""
    st.dataframe(tab, height=35 * (len(tab) + 1) + 3,
                 column_config={"_index": st.column_config.TextColumn(width="large")},  # nomes das contas inteiros
                 **opcoes)


def milhoes(v):
    """Formata um valor em reais como milhões no padrão brasileiro."""
    return "—" if pd.isna(v) else relatorio._br(v / 1e6, 1)


# ---------------------------------------------------------------------------
# Relatórios para download (mesmos arquivos gerados pelo main.py)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def gerar_arquivos(_r, chave):
    """Gera o HTML e o Excel numa pasta temporária e devolve os bytes de cada um.
    `chave` identifica a análise para o cache (o dicionário `_r` não entra no hash)."""
    with tempfile.TemporaryDirectory() as pasta:
        html, xlsx = Path(pasta) / "relatorio.html", Path(pasta) / "relatorio.xlsx"
        relatorio.gerar_html(_r["df"], _r["ind"], _r["diag"], _r["meta"], _r["mercado"], html)
        relatorio.gerar_excel(_r["df"], _r["ind"], _r["diag"], xlsx)
        return html.read_bytes(), xlsx.read_bytes()


# ---------------------------------------------------------------------------
# Tela de resultados
# ---------------------------------------------------------------------------

def cartoes(ind):
    """Linha de cartões com os principais índices do último ano e a variação
    em relação ao ano anterior (verde = melhora, vermelho = piora)."""
    anos = list(ind.columns)
    atual, anterior = anos[-1], (anos[-2] if len(anos) > 1 else None)
    # (chave, unidade, True se subir é bom)
    destaques = [("roe", "%", True), ("margem_liquida", "%", True), ("liquidez_corrente", "x", True),
                 ("divida_liquida_ebitda", "x", False), ("ciclo_caixa", "dias", False)]
    for coluna, (chave, unidade, subir_bom) in zip(st.columns(len(destaques)), destaques):
        valor = ind.at[chave, atual]
        delta = None
        if anterior is not None and not pd.isna(valor) and not pd.isna(ind.at[chave, anterior]):
            dif = valor - ind.at[chave, anterior]
            # variação de percentuais em pontos percentuais (p.p.); demais na própria unidade
            delta = f"{relatorio._br(dif * 100, 1)} p.p." if unidade == "%" else relatorio.formatar(dif, unidade)
            delta = ("+" if dif > 0 else "") + delta
        coluna.metric(indicadores.POR_CHAVE[chave].nome.split(" - ")[0], relatorio.formatar(valor, unidade),
                      delta, delta_color="normal" if subir_bom else "inverse",
                      help=f"{indicadores.POR_CHAVE[chave].formula} · variação em relação a {anterior}" if anterior else None)


def mostrar_resultados(r):
    """Etapa 3: apresenta diagnóstico, indicadores, demonstrações e análises em abas."""
    df, ind, meta = r["df"], r["ind"], r["meta"]
    anos = list(df.columns)

    st.title(meta["nome"])
    detalhes = [meta["fonte"], f"exercícios {anos[0]}–{anos[-1]}", f"demonstrações: {meta['tipo_demonstracao']}"]
    if meta.get("cd_cvm"):
        detalhes.append(f"código CVM {meta['cd_cvm']}")
    if r["mercado"]:
        detalhes.append(f"valor de mercado {relatorio.formatar(r['mercado']['valor_mercado'], 'R$')} ({r['mercado']['fonte']})")
    st.caption(" · ".join(detalhes))

    cartoes(ind)

    aba_diag, aba_ind, aba_dem, aba_dupont, aba_vh = st.tabs(
        ["Diagnóstico", "Indicadores", "Demonstrações", "DuPont", "Vertical e horizontal"])

    with aba_diag:
        st.caption("Comentários gerados automaticamente a partir de regras simples; os limites são referências "
                   "didáticas, o ideal é comparar com empresas do mesmo setor.")
        for nivel, texto in r["diag"]:
            caixa, icone = CAIXA_DIAGNOSTICO[nivel]
            caixa(texto, icon=icone)
        ebitda = df.loc["ebit"] + df.loc["depreciacao"].abs().fillna(0)
        c1, c2 = st.columns(2)
        c1.plotly_chart(grafico_barras(df, [("Receita", df.loc["receita"] / 1e6), ("EBITDA", ebitda / 1e6),
                                            ("Lucro líquido", df.loc["lucro_liquido"] / 1e6)],
                                       "Resultado (R$ milhões)"), width="stretch")
        c2.plotly_chart(grafico_linhas(ind, ["margem_bruta", "margem_ebitda", "margem_operacional", "margem_liquida"],
                                       "Margens", "%"), width="stretch")

    with aba_ind:
        c1, c2 = st.columns(2)
        c1.plotly_chart(grafico_linhas(ind, ["liquidez_corrente", "liquidez_seca", "liquidez_imediata"],
                                       "Liquidez (linha tracejada = 1,0x)", "x", referencia=1), width="stretch")
        c2.plotly_chart(grafico_linhas(ind, ["prazo_recebimento", "prazo_estoque", "prazo_pagamento", "ciclo_caixa"],
                                       "Prazos médios e ciclo de caixa (dias)", "dias"), width="stretch")
        estrutura = [(captura.DESCRICAO_CONTAS[c], df.loc[c] / df.loc["passivo_total"] * 100)
                     for c in ["passivo_circulante", "passivo_nao_circulante", "patrimonio_liquido"]]
        c1.plotly_chart(grafico_barras(df, estrutura, "Estrutura de financiamento (% do passivo total)", empilhado=True),
                        width="stretch")
        fluxos = [("Operacional", df.loc["fco"] / 1e6), ("Investimento", df.loc["fci"] / 1e6),
                  ("Financiamento", df.loc["fcf"] / 1e6)]
        c2.plotly_chart(grafico_barras(df, fluxos, "Fluxos de caixa por atividade (R$ milhões)"), width="stretch")
        tabelas_indicadores(ind)

    with aba_dem:
        st.caption("Valores em R$ milhões. Sinais conforme a CVM: custos, despesas e saídas de caixa são negativos.")
        st.subheader("Balanço patrimonial")
        mostrar_tabela(tabela_contas(df, ["ativo_total", "ativo_circulante", "caixa", "aplicacoes_financeiras",
                                        "contas_receber", "estoques", "ativo_nao_circulante", "imobilizado",
                                        "passivo_total", "passivo_circulante", "fornecedores", "emprestimos_cp",
                                        "passivo_nao_circulante", "emprestimos_lp", "patrimonio_liquido"], milhoes),
                     width="stretch")
        checagem = indicadores.verificar_balanco(df)
        st.caption("Verificação da Eq. 2.1 — (Ativo − Passivo total) ÷ Ativo: "
                   + ", ".join(f"{a}: {relatorio.formatar(v, '%')}" for a, v in checagem.items()))
        st.subheader("Demonstração do resultado")
        mostrar_tabela(tabela_contas(df, ["receita", "custo", "lucro_bruto", "ebit", "receitas_financeiras",
                                        "despesas_financeiras", "lucro_antes_ir", "ir_csll", "lucro_liquido"], milhoes),
                     width="stretch")
        st.subheader("Fluxos de caixa (itens selecionados)")
        mostrar_tabela(tabela_contas(df, ["fco", "depreciacao", "fci", "fcf", "dividendos_pagos"], milhoes),
                     width="stretch")

    with aba_dupont:
        st.markdown("O ROE é decomposto em três fatores (Eq. 2.18): quanto a empresa lucra por real vendido "
                    "(**margem**), quanto vende por real de ativos (**giro**) e quanto dos ativos é financiado "
                    "por terceiros (**multiplicador do PL**). Assim dá para ver *por que* o retorno mudou.")
        grafico_dupont(df)

    with aba_vh:
        vertical = indicadores.analise_vertical(df)
        percentual = lambda v: relatorio.formatar(v, "%")
        st.subheader("Análise vertical")
        st.caption("Contas do balanço em % do ativo total; contas da DRE em % da receita.")
        mostrar_tabela(tabela_contas(vertical, vertical.index, percentual), width="stretch")
        st.subheader("Análise horizontal")
        st.caption("Variação % em relação ao ano anterior.")
        mostrar_tabela(tabela_contas(indicadores.analise_horizontal(df), vertical.index, percentual),
                     width="stretch")

    # Downloads dos mesmos relatórios gerados pela versão de terminal
    st.divider()
    html, xlsx = gerar_arquivos(r, r["chave"])
    nome = "".join(c if c.isalnum() else "_" for c in captura._sem_acento(meta["nome"]))[:40]
    c1, c2, _ = st.columns([1, 1, 3])
    c1.download_button("⬇ Relatório HTML", html, f"relatorio_{nome}.html", "text/html", width="stretch")
    c2.download_button("⬇ Planilha Excel", xlsx, f"relatorio_{nome}.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")


# ---------------------------------------------------------------------------
# Programa principal
# ---------------------------------------------------------------------------

pedido = formulario()
if pedido is not None:
    with st.spinner("Capturando dados e calculando indicadores..."):
        try:
            resultado = executar(pedido)
            # A chave identifica esta análise (usada no cache dos arquivos para download)
            resultado["chave"] = repr({k: v for k, v in pedido.items() if k != "arquivo"}) + \
                (pedido["arquivo"].file_id if pedido.get("arquivo") else "")
            st.session_state["resultado"] = resultado  # mantém o resultado ao trocar de aba ou baixar
        except Exception as erro:
            st.session_state.pop("resultado", None)
            st.error(f"Erro na captura: {erro}")

if "resultado" in st.session_state:
    mostrar_resultados(st.session_state["resultado"])
elif pedido is None:
    st.title("Análise de Demonstrações Financeiras")
    st.markdown(
        "Escolha a fonte dos dados na barra lateral e clique em **Analisar**.\n\n"
        "- **CVM**: demonstrações oficiais de companhias abertas brasileiras (requer internet);\n"
        "- **Arquivo CSV**: dados de qualquer empresa, no formato do modelo;\n"
        "- **Empresa de exemplo**: dados fictícios, funciona sem internet.\n\n"
        "Os índices seguem o Capítulo 2 de Berk, DeMarzo & Harford, *Fundamentos de Finanças Empresariais*.")
