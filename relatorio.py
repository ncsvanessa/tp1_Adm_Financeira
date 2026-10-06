"""
relatorio.py
============
Módulo de GERAÇÃO DE RELATÓRIOS.

A cada execução são gerados:
    1. Resumo no terminal (principais índices e diagnóstico);
    2. Relatório HTML autocontido (gráficos embutidos), que abre em
       qualquer navegador e pode ser impresso em PDF;
    3. Planilha Excel com todas as tabelas (demonstrações, índices,
       análises vertical e horizontal, DuPont e diagnóstico), para que o
       usuário possa conferir os cálculos.
"""

import base64
import html
import io
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # backend sem janela: permite gerar gráficos em qualquer ambiente
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from captura import DESCRICAO_CONTAS
from indicadores import POR_CHAVE, analise_horizontal, analise_vertical, dupont, verificar_balanco

# Paleta de cores usada em todos os gráficos
CORES = ["#1f4e79", "#2e8b57", "#c0504d", "#e3a21a", "#7f6084", "#4bacc6"]


# ---------------------------------------------------------------------------
# Formatação de números no padrão brasileiro
# ---------------------------------------------------------------------------

def _br(numero, casas=2):
    """Formata número no padrão brasileiro: 1.234,56"""
    texto = f"{numero:,.{casas}f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def formatar(valor, unidade):
    """Formata um valor de acordo com sua unidade ('R$', '%', 'x', 'dias')."""
    if valor is None or pd.isna(valor):
        return "—"
    if unidade == "R$":
        return f"R$ {_br(valor / 1e6, 1)} mi"      # valores monetários em milhões
    if unidade == "%":
        return f"{_br(valor * 100, 1)}%"
    if unidade == "dias":
        return f"{_br(valor, 0)} dias"
    return f"{_br(valor, 2)}x"


# ---------------------------------------------------------------------------
# Gráficos
# ---------------------------------------------------------------------------

def _figura_base64(fig):
    """Converte uma figura do matplotlib em imagem PNG codificada em base64,
    para ser embutida diretamente no HTML (o relatório fica em um único arquivo)."""
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _estilo(ax, titulo, ylabel=None):
    """Aplica um estilo visual uniforme a um eixo."""
    ax.set_title(titulo, fontsize=11, fontweight="bold", loc="left")
    if ylabel:
        ax.set_ylabel(ylabel)
    ax.grid(axis="y", alpha=0.3)
    ax.spines[["top", "right"]].set_visible(False)


def gerar_graficos(df, ind):
    """Gera todos os gráficos do relatório. Retorna dict nome -> PNG base64."""
    anos = [str(a) for a in df.columns]
    graficos = {}
    x = np.arange(len(anos))

    # 1) Receita, EBITDA e lucro líquido
    fig, ax = plt.subplots(figsize=(7, 3.6))
    ebitda = df.loc["ebit"] + df.loc["depreciacao"].abs().fillna(0)
    series = [("Receita", df.loc["receita"]), ("EBITDA", ebitda), ("Lucro líquido", df.loc["lucro_liquido"])]
    largura = 0.27
    for i, (nome, s) in enumerate(series):
        ax.bar(x + (i - 1) * largura, s / 1e6, largura, label=nome, color=CORES[i])
    ax.set_xticks(x, anos)
    _estilo(ax, "Resultado (R$ milhões)")
    ax.legend(frameon=False, fontsize=8)
    graficos["resultado"] = _figura_base64(fig)

    # 2) Margens
    fig, ax = plt.subplots(figsize=(7, 3.6))
    for i, chave in enumerate(["margem_bruta", "margem_ebitda", "margem_operacional", "margem_liquida"]):
        if chave in ind.index:
            ax.plot(anos, ind.loc[chave] * 100, marker="o", label=POR_CHAVE[chave].nome, color=CORES[i])
    _estilo(ax, "Margens (%)", "%")
    ax.legend(frameon=False, fontsize=8)
    graficos["margens"] = _figura_base64(fig)

    # 3) Liquidez
    fig, ax = plt.subplots(figsize=(7, 3.6))
    for i, chave in enumerate(["liquidez_corrente", "liquidez_seca", "liquidez_imediata"]):
        ax.plot(anos, ind.loc[chave], marker="o", label=POR_CHAVE[chave].nome, color=CORES[i])
    ax.axhline(1, color="gray", linestyle="--", linewidth=1)  # referência: índice = 1
    _estilo(ax, "Índices de liquidez (x)")
    ax.legend(frameon=False, fontsize=8)
    graficos["liquidez"] = _figura_base64(fig)

    # 4) Estrutura de capital: composição do passivo + PL em cada ano
    fig, ax = plt.subplots(figsize=(7, 3.6))
    base = np.zeros(len(anos))
    for i, conta in enumerate(["passivo_circulante", "passivo_nao_circulante", "patrimonio_liquido"]):
        valores = (df.loc[conta] / df.loc["passivo_total"] * 100).fillna(0).values
        ax.bar(anos, valores, bottom=base, label=DESCRICAO_CONTAS[conta], color=CORES[i])
        base += valores
    _estilo(ax, "Estrutura de financiamento (% do passivo total)", "%")
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    graficos["estrutura"] = _figura_base64(fig)

    # 5) Decomposição DuPont (Eq. 2.18)
    dp = dupont(df)
    fig, eixos = plt.subplots(1, 4, figsize=(11, 2.8))
    titulos = [("margem_liquida", "Margem líquida (%)", 100), ("giro_ativos", "Giro dos ativos (x)", 1),
               ("multiplicador_pl", "Multiplicador do PL (x)", 1), ("roe", "= ROE (%)", 100)]
    for ax, (chave, titulo, fator) in zip(eixos, titulos):
        ax.bar(anos, dp.loc[chave] * fator, color=CORES[3] if chave == "roe" else CORES[0])
        _estilo(ax, titulo)
        ax.tick_params(labelsize=8)
    fig.suptitle("Análise DuPont: ROE = Margem × Giro × Alavancagem", fontsize=11, x=0.01, ha="left")
    fig.tight_layout()
    graficos["dupont"] = _figura_base64(fig)

    # 6) Ciclo de caixa
    fig, ax = plt.subplots(figsize=(7, 3.6))
    for i, chave in enumerate(["prazo_recebimento", "prazo_estoque", "prazo_pagamento", "ciclo_caixa"]):
        ax.plot(anos, ind.loc[chave], marker="o", label=POR_CHAVE[chave].nome, color=CORES[i])
    _estilo(ax, "Prazos médios e ciclo de caixa (dias)", "dias")
    ax.legend(frameon=False, fontsize=8)
    graficos["ciclo"] = _figura_base64(fig)

    # 7) Fluxos de caixa por atividade (Seção 2.6)
    fig, ax = plt.subplots(figsize=(7, 3.6))
    for i, (conta, nome) in enumerate([("fco", "Operacional"), ("fci", "Investimento"), ("fcf", "Financiamento")]):
        ax.bar(x + (i - 1) * largura, df.loc[conta] / 1e6, largura, label=nome, color=CORES[i])
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xticks(x, anos)
    _estilo(ax, "Fluxos de caixa por atividade (R$ milhões)")
    ax.legend(frameon=False, fontsize=8)
    graficos["fluxos"] = _figura_base64(fig)

    return graficos


# ---------------------------------------------------------------------------
# Tabelas HTML
# ---------------------------------------------------------------------------

def _tabela_demonstracoes(df, contas, titulo):
    """Tabela HTML com um subconjunto de contas, em R$ milhões."""
    cab = "".join(f"<th>{a}</th>" for a in df.columns)
    linhas = ""
    for conta in contas:
        valores = "".join(
            f"<td>{'—' if pd.isna(v) else _br(v / 1e6, 1)}</td>" for v in df.loc[conta])
        linhas += f"<tr><td class='rot'>{html.escape(DESCRICAO_CONTAS[conta])}</td>{valores}</tr>"
    return (f"<h3>{titulo}</h3><table><tr><th class='rot'>Conta (R$ milhões)</th>{cab}</tr>"
            f"{linhas}</table>")


def _tabela_indicadores(ind):
    """Tabela HTML dos indicadores, agrupados por categoria, com fórmula e referência."""
    anos = list(ind.columns)
    cab = "".join(f"<th>{a}</th>" for a in anos)
    corpo, categoria_atual = "", None
    for chave in ind.index:
        meta = POR_CHAVE[chave]
        if meta.categoria != categoria_atual:  # nova categoria -> linha de título
            categoria_atual = meta.categoria
            corpo += f"<tr class='cat'><td colspan='{len(anos) + 3}'>{categoria_atual}</td></tr>"
        valores = "".join(f"<td>{formatar(v, meta.unidade)}</td>" for v in ind.loc[chave])
        corpo += (f"<tr><td class='rot'>{meta.nome}</td><td class='formula'>{html.escape(meta.formula)}</td>"
                  f"<td class='ref'>{meta.referencia}</td>{valores}</tr>")
    return (f"<table><tr><th class='rot'>Indicador</th><th>Fórmula</th><th>Ref. (Berk)</th>{cab}</tr>"
            f"{corpo}</table>")


def _tabela_percentual(tab, titulo, nota):
    """Tabela HTML de percentuais (análises vertical e horizontal)."""
    cab = "".join(f"<th>{a}</th>" for a in tab.columns)
    linhas = ""
    for conta in tab.index:
        valores = "".join(f"<td>{formatar(v, '%')}</td>" for v in tab.loc[conta])
        linhas += f"<tr><td class='rot'>{html.escape(DESCRICAO_CONTAS[conta])}</td>{valores}</tr>"
    return (f"<h3>{titulo}</h3><p class='nota'>{nota}</p>"
            f"<table><tr><th class='rot'>Conta</th>{cab}</tr>{linhas}</table>")


# ---------------------------------------------------------------------------
# Relatório HTML
# ---------------------------------------------------------------------------

CSS = """
body{font-family:Segoe UI,Helvetica,Arial,sans-serif;max-width:1100px;margin:auto;padding:24px;color:#222}
h1{color:#1f4e79;margin-bottom:4px} h2{color:#1f4e79;border-bottom:2px solid #1f4e79;padding-bottom:4px;margin-top:36px}
h3{margin-bottom:6px} table{border-collapse:collapse;width:100%;font-size:13px;margin-bottom:16px}
th,td{border:1px solid #ddd;padding:5px 8px;text-align:right} th{background:#1f4e79;color:#fff}
td.rot,th.rot{text-align:left} td.formula{text-align:left;color:#555;font-size:12px}
td.ref{text-align:center;color:#555;font-size:12px} tr.cat td{background:#e8eef5;font-weight:bold;text-align:left}
tr:nth-child(even) td{background:#fafafa} .meta{color:#555} .nota{color:#666;font-size:12px}
.diag{padding:8px 12px;margin:6px 0;border-left:5px solid;border-radius:3px}
.ok{border-color:#2e8b57;background:#eef8f1} .atencao{border-color:#e3a21a;background:#fdf6e6}
.alerta{border-color:#c0504d;background:#fbeeee} .info{border-color:#1f4e79;background:#eef3f9}
.grade{display:grid;grid-template-columns:1fr 1fr;gap:12px} img{max-width:100%}
@media(max-width:800px){.grade{grid-template-columns:1fr}}
"""

ROTULO_NIVEL = {"ok": "✔ Positivo", "atencao": "⚠ Atenção", "alerta": "✖ Alerta", "info": "ℹ Informação"}


def gerar_html(df, ind, diag, meta, mercado, caminho):
    """Monta o relatório HTML completo e grava em `caminho`."""
    g = gerar_graficos(df, ind)
    img = lambda nome: f"<img src='data:image/png;base64,{g[nome]}'>"
    anos = list(df.columns)

    # Cabeçalho com identificação da empresa e da fonte
    info_empresa = f"<b>Fonte dos dados:</b> {html.escape(meta['fonte'])}"
    if meta.get("cd_cvm"):
        info_empresa += f" &nbsp;|&nbsp; <b>Código CVM:</b> {meta['cd_cvm']}"
    if meta.get("cnpj"):
        info_empresa += f" &nbsp;|&nbsp; <b>CNPJ:</b> {meta['cnpj']}"
    info_empresa += f" &nbsp;|&nbsp; <b>Demonstrações:</b> {meta['tipo_demonstracao']}"
    if mercado:
        info_empresa += (f"<br><b>Dados de mercado:</b> {html.escape(mercado['fonte'])} — "
                         f"valor de mercado {formatar(mercado['valor_mercado'], 'R$')}")

    diag_html = "".join(f"<div class='diag {n}'><b>{ROTULO_NIVEL[n]}:</b> {html.escape(t)}</div>"
                        for n, t in diag)

    bp = ["ativo_circulante", "caixa", "aplicacoes_financeiras", "contas_receber", "estoques",
          "ativo_nao_circulante", "imobilizado", "ativo_total", "passivo_circulante", "fornecedores",
          "emprestimos_cp", "passivo_nao_circulante", "emprestimos_lp", "patrimonio_liquido", "passivo_total"]
    dre = ["receita", "custo", "lucro_bruto", "ebit", "receitas_financeiras", "despesas_financeiras",
           "lucro_antes_ir", "ir_csll", "lucro_liquido"]
    dfc = ["fco", "depreciacao", "fci", "fcf", "dividendos_pagos"]

    checagem = verificar_balanco(df)
    texto_checagem = ", ".join(f"{a}: {formatar(v, '%')}" for a, v in checagem.items())

    pagina = f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Análise de Demonstrações Financeiras — {html.escape(meta['nome'])}</title><style>{CSS}</style></head><body>
<h1>Análise de Demonstrações Financeiras</h1>
<h2 style="margin-top:4px;border:none">{html.escape(meta['nome'])} — exercícios {anos[0]} a {anos[-1]}</h2>
<p class="meta">{info_empresa}<br><b>Gerado em:</b> {datetime.now():%d/%m/%Y %H:%M}</p>

<h2>1. Diagnóstico</h2>
<p class="nota">Comentários gerados automaticamente a partir de regras simples. Os limites usados são
referências didáticas: o ideal é comparar com empresas do mesmo setor.</p>
{diag_html}

<h2>2. Visão geral</h2>
<div class="grade">{img('resultado')}{img('margens')}</div>

<h2>3. Demonstrações financeiras resumidas</h2>
{_tabela_demonstracoes(df, bp, "Balanço Patrimonial")}
<p class="nota">Verificação da Eq. 2.1 (Ativo − Passivo total) ÷ Ativo: {texto_checagem}</p>
{_tabela_demonstracoes(df, dre, "Demonstração do Resultado")}
{_tabela_demonstracoes(df, dfc, "Demonstração dos Fluxos de Caixa (itens selecionados)")}

<h2>4. Indicadores financeiros</h2>
{_tabela_indicadores(ind)}
<div class="grade">{img('liquidez')}{img('estrutura')}{img('ciclo')}{img('fluxos')}</div>

<h2>5. Análise DuPont do ROE (Eq. 2.18)</h2>
<p>O ROE é decomposto em três fatores: quanto a empresa lucra por real vendido (margem líquida), quanto
ela vende por real investido em ativos (giro) e quanto dos ativos é financiado por capital de terceiros
(multiplicador do PL). Isso permite identificar <i>por que</i> o retorno ao acionista mudou.</p>
{img('dupont')}

<h2>6. Análises vertical e horizontal</h2>
{_tabela_percentual(analise_vertical(df), "Análise vertical",
                    "Contas do balanço em % do Ativo Total; contas da DRE em % da Receita.")}
{_tabela_percentual(analise_horizontal(df).loc[analise_vertical(df).index], "Análise horizontal",
                    "Variação % em relação ao ano anterior.")}

<h2>7. Notas metodológicas</h2>
<ul class="nota">
<li>Valores em reais, exibidos em milhões. Sinais conforme a CVM: custos, despesas e saídas de caixa são negativos.</li>
<li>Os índices usam saldos de final de período (não médias), como nos exemplos do Cap. 2 de Berk, DeMarzo &amp; Harford.</li>
<li>Dívida = empréstimos e financiamentos (inclui debêntures); arrendamentos (IFRS 16) não estão incluídos.</li>
<li>EBITDA = EBIT + depreciação e amortização obtida na DFC. O ROA segue a definição do livro: (Lucro líquido + Juros) ÷ Ativo.</li>
<li>ROIC usa a alíquota efetiva de IR/CSLL (ou 34% quando ela não pode ser calculada).</li>
<li>Índices de mercado usam a cotação atual e são calculados apenas para o último exercício.</li>
<li>O plano de contas utilizado é o de empresas não financeiras; bancos e seguradoras não são suportados.</li>
</ul>
</body></html>"""
    Path(caminho).write_text(pagina, encoding="utf-8")


# ---------------------------------------------------------------------------
# Planilha Excel
# ---------------------------------------------------------------------------

def gerar_excel(df, ind, diag, caminho):
    """Grava as tabelas da análise em uma planilha Excel (uma aba por tabela)."""
    rotular = lambda tab: tab.rename(index=lambda k: DESCRICAO_CONTAS.get(k, k))
    ind_nomes = ind.copy()
    ind_nomes.insert(0, "Unidade", [POR_CHAVE[k].unidade for k in ind.index])
    ind_nomes.insert(0, "Fórmula", [POR_CHAVE[k].formula for k in ind.index])
    ind_nomes.index = [POR_CHAVE[k].nome for k in ind.index]

    with pd.ExcelWriter(caminho, engine="openpyxl") as escritor:
        rotular(df).to_excel(escritor, sheet_name="Demonstracoes")
        ind_nomes.to_excel(escritor, sheet_name="Indicadores")
        rotular(analise_vertical(df)).to_excel(escritor, sheet_name="Analise_Vertical")
        rotular(analise_horizontal(df)).to_excel(escritor, sheet_name="Analise_Horizontal")
        dupont(df).to_excel(escritor, sheet_name="DuPont")
        pd.DataFrame(diag, columns=["Nivel", "Comentario"]).to_excel(escritor, sheet_name="Diagnostico", index=False)
        # Ajusta a largura da primeira coluna para facilitar a leitura
        for aba in escritor.book.worksheets:
            aba.column_dimensions["A"].width = 48


# ---------------------------------------------------------------------------
# Saída no terminal
# ---------------------------------------------------------------------------

def imprimir_resumo(ind, diag, meta):
    """Mostra no terminal uma tabela com os índices e o diagnóstico."""
    print("\n" + "=" * 78)
    print(f" {meta['nome']}  |  {meta['fonte']}")
    print("=" * 78)
    categoria = None
    for chave in ind.index:
        m = POR_CHAVE[chave]
        if m.categoria != categoria:
            categoria = m.categoria
            print(f"\n[{categoria}]")
            print(f"  {'':46}" + "".join(f"{a:>14}" for a in ind.columns))
        print(f"  {m.nome[:46]:46}" + "".join(f"{formatar(v, m.unidade):>14}" for v in ind.loc[chave]))
    print("\nDIAGNÓSTICO")
    for nivel, texto in diag:
        print(f"  {ROTULO_NIVEL[nivel]:<15} {texto}")
    print()
