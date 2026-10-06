"""
indicadores.py
==============
Módulo de CÁLCULO dos indicadores da análise de demonstrações financeiras.

Os índices seguem o Capítulo 2 de Berk, DeMarzo & Harford,
"Fundamentos de Finanças Empresariais" (material do curso). Quando um
índice tem equação numerada no livro, o número aparece em `referencia`.
Alguns indicadores complementares, muito usados na prática brasileira
(liquidez imediata, ciclo de caixa, dívida líquida/EBITDA etc.), também
foram incluídos e estão marcados como "complementar".

Além dos índices, o módulo produz:
    - análise vertical  (cada conta como % do ativo total ou da receita);
    - análise horizontal (variação % de cada conta em relação ao ano anterior);
    - decomposição DuPont do ROE (Eq. 2.18);
    - um diagnóstico textual automático, baseado em regras simples.

Convenção: o DataFrame de entrada segue o formato do módulo captura.py
(linhas = contas padronizadas, colunas = anos, sinais da CVM).
"""

import re
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

DIAS_ANO = 365          # base de dias usada nos prazos médios (Berk usa 365)
ALIQUOTA_PADRAO = 0.34  # IR (25%) + CSLL (9%): usada se a alíquota efetiva não puder ser calculada


# ---------------------------------------------------------------------------
# Funções auxiliares de cálculo
# ---------------------------------------------------------------------------

def div(a, b):
    """Divisão "segura": devolve NaN se o divisor for zero ou ausente."""
    if b is None or a is None or pd.isna(a) or pd.isna(b) or b == 0:
        return np.nan
    return a / b


def soma(*valores):
    """Soma ignorando valores ausentes; devolve NaN se TODOS forem ausentes."""
    validos = [v for v in valores if not pd.isna(v)]
    return sum(validos) if validos else np.nan


def divida_total(d):
    """Dívida financeira bruta = empréstimos e financiamentos de curto + longo prazo."""
    return soma(d["emprestimos_cp"], d["emprestimos_lp"])


def caixa_total(d):
    """Caixa e equivalentes + aplicações financeiras de curto prazo."""
    return soma(d["caixa"], d["aplicacoes_financeiras"])


def divida_liquida(d):
    """Dívida líquida = dívida bruta - caixa (negativa => empresa tem 'caixa líquido')."""
    return divida_total(d) - caixa_total(d)


def ebitda(d):
    """EBITDA = EBIT + depreciação e amortização (Seção 2.5)."""
    return soma(d["ebit"], abs(d["depreciacao"]) if not pd.isna(d["depreciacao"]) else np.nan)


def juros(d):
    """Despesa de juros (despesas financeiras), em valor positivo."""
    return abs(d["despesas_financeiras"]) if not pd.isna(d["despesas_financeiras"]) else np.nan


def aliquota_efetiva(d):
    """
    Alíquota efetiva de IR/CSLL = |IR| / LAIR.
    Se o LAIR for negativo ou a alíquota sair de uma faixa plausível (0 a 50%),
    usa a alíquota nominal brasileira de 34%.
    """
    t = div(abs(d["ir_csll"]) if not pd.isna(d["ir_csll"]) else np.nan, d["lucro_antes_ir"])
    if pd.isna(t) or d["lucro_antes_ir"] <= 0 or not (0 <= t <= 0.5):
        return ALIQUOTA_PADRAO
    return t


# ---------------------------------------------------------------------------
# Definição dos indicadores
# ---------------------------------------------------------------------------

@dataclass
class Indicador:
    """Descreve um indicador: como calcular, como exibir e onde está no livro."""
    chave: str            # identificador interno
    nome: str             # nome exibido no relatório
    categoria: str        # grupo do relatório
    unidade: str          # 'x' (vezes), '%', 'dias' ou 'R$'
    formula: str          # fórmula em texto, exibida no relatório
    referencia: str       # equação/seção do Berk ou "complementar"
    calcular: Callable    # função f(d, mercado) -> valor
    usa_mercado: bool = False  # True se depende do valor de mercado


# Cada função recebe:
#   d       -> pandas.Series com as contas de UM ano
#   mercado -> dicionário de captura.capturar_mercado() (ou None)
INDICADORES = [
    # ---------------- Liquidez (Seção 2.3) ----------------
    Indicador("capital_giro_liquido", "Capital de giro líquido", "Liquidez", "R$",
              "Ativo circulante − Passivo circulante", "Eq. 2.2",
              lambda d, m: d["ativo_circulante"] - d["passivo_circulante"]),
    Indicador("liquidez_corrente", "Liquidez corrente", "Liquidez", "x",
              "Ativo circulante ÷ Passivo circulante", "Eq. 2.6",
              lambda d, m: div(d["ativo_circulante"], d["passivo_circulante"])),
    Indicador("liquidez_seca", "Liquidez seca (acid-test)", "Liquidez", "x",
              "(Ativo circulante − Estoques) ÷ Passivo circulante", "Eq. 2.7",
              lambda d, m: div(d["ativo_circulante"] - soma(d["estoques"], 0), d["passivo_circulante"])),
    Indicador("liquidez_imediata", "Liquidez imediata", "Liquidez", "x",
              "(Caixa + Aplicações financeiras) ÷ Passivo circulante", "complementar",
              lambda d, m: div(caixa_total(d), d["passivo_circulante"])),

    # ---------------- Rentabilidade / margens (Seção 2.5) ----------------
    Indicador("margem_bruta", "Margem bruta", "Margens", "%",
              "Lucro bruto ÷ Receita", "Eq. 2.9",
              lambda d, m: div(d["lucro_bruto"], d["receita"])),
    Indicador("margem_ebitda", "Margem EBITDA", "Margens", "%",
              "EBITDA ÷ Receita", "Seção 2.5",
              lambda d, m: div(ebitda(d), d["receita"])),
    Indicador("margem_operacional", "Margem operacional", "Margens", "%",
              "EBIT ÷ Receita", "Eq. 2.10",
              lambda d, m: div(d["ebit"], d["receita"])),
    Indicador("margem_liquida", "Margem líquida", "Margens", "%",
              "Lucro líquido ÷ Receita", "Eq. 2.11",
              lambda d, m: div(d["lucro_liquido"], d["receita"])),

    # ---------------- Eficiência e capital de giro (Seção 2.5) ----------------
    Indicador("giro_ativos", "Giro dos ativos", "Eficiência e capital de giro", "x",
              "Receita ÷ Ativo total", "Eq. 2.12",
              lambda d, m: div(d["receita"], d["ativo_total"])),
    Indicador("giro_ativos_fixos", "Giro dos ativos fixos", "Eficiência e capital de giro", "x",
              "Receita ÷ Imobilizado", "Eq. 2.13",
              lambda d, m: div(d["receita"], d["imobilizado"])),
    Indicador("prazo_recebimento", "Prazo médio de recebimento", "Eficiência e capital de giro", "dias",
              "Contas a receber ÷ (Receita ÷ 365)", "Eq. 2.14",
              lambda d, m: div(d["contas_receber"], div(d["receita"], DIAS_ANO))),
    Indicador("giro_estoque", "Giro do estoque", "Eficiência e capital de giro", "x",
              "Custo das vendas ÷ Estoques", "Eq. 2.15",
              lambda d, m: div(abs(d["custo"]), d["estoques"])),
    Indicador("prazo_estoque", "Prazo médio de estocagem", "Eficiência e capital de giro", "dias",
              "Estoques ÷ (Custo das vendas ÷ 365)", "complementar",
              lambda d, m: div(d["estoques"], div(abs(d["custo"]), DIAS_ANO))),
    Indicador("prazo_pagamento", "Prazo médio de pagamento", "Eficiência e capital de giro", "dias",
              "Fornecedores ÷ (Custo das vendas ÷ 365)", "complementar",
              lambda d, m: div(d["fornecedores"], div(abs(d["custo"]), DIAS_ANO))),
    Indicador("ciclo_caixa", "Ciclo de caixa (financeiro)", "Eficiência e capital de giro", "dias",
              "Prazo receb. + Prazo estocagem − Prazo pagamento", "complementar",
              lambda d, m: (div(d["contas_receber"], div(d["receita"], DIAS_ANO))
                            + div(d["estoques"], div(abs(d["custo"]), DIAS_ANO))
                            - div(d["fornecedores"], div(abs(d["custo"]), DIAS_ANO)))),

    # ---------------- Alavancagem (Seções 2.3 e 2.5) ----------------
    Indicador("divida_total", "Dívida financeira bruta", "Alavancagem", "R$",
              "Empréstimos e financiamentos (CP + LP)", "Seção 2.3",
              lambda d, m: divida_total(d)),
    Indicador("divida_liquida", "Dívida líquida", "Alavancagem", "R$",
              "Dívida bruta − Caixa − Aplicações financeiras", "Seção 2.3",
              lambda d, m: divida_liquida(d)),
    Indicador("divida_pl", "Capital de terceiros / capital próprio", "Alavancagem", "x",
              "Dívida total ÷ Patrimônio líquido (contábil)", "Eq. 2.4",
              lambda d, m: div(divida_total(d), d["patrimonio_liquido"])),
    Indicador("divida_liquida_ebitda", "Dívida líquida / EBITDA", "Alavancagem", "x",
              "Dívida líquida ÷ EBITDA", "complementar",
              lambda d, m: div(divida_liquida(d), ebitda(d))),
    Indicador("cobertura_juros", "Cobertura de juros (EBIT)", "Alavancagem", "x",
              "EBIT ÷ Despesas financeiras", "Seção 2.5",
              lambda d, m: div(d["ebit"], juros(d))),
    Indicador("endividamento_geral", "Endividamento geral", "Alavancagem", "%",
              "(Passivo circulante + Passivo não circulante) ÷ Ativo total", "complementar",
              lambda d, m: div(soma(d["passivo_circulante"], d["passivo_nao_circulante"]), d["ativo_total"])),
    Indicador("multiplicador_pl", "Multiplicador do PL (alavancagem de capital)", "Alavancagem", "x",
              "Ativo total ÷ Patrimônio líquido", "Eq. 2.18",
              lambda d, m: div(d["ativo_total"], d["patrimonio_liquido"])),

    # ---------------- Retorno sobre investimento (Seção 2.5) ----------------
    Indicador("roe", "ROE - retorno sobre o patrimônio", "Retorno", "%",
              "Lucro líquido ÷ Patrimônio líquido", "Eq. 2.16",
              lambda d, m: div(d["lucro_liquido"], d["patrimonio_liquido"])),
    Indicador("roa", "ROA - retorno sobre os ativos", "Retorno", "%",
              "(Lucro líquido + Juros) ÷ Ativo total", "Eq. 2.17",
              lambda d, m: div(soma(d["lucro_liquido"], juros(d)), d["ativo_total"])),
    Indicador("roic", "ROIC - retorno sobre o capital investido", "Retorno", "%",
              "EBIT × (1 − alíquota) ÷ (PL + Dívida líquida)", "Seção 2.5",
              lambda d, m: div(d["ebit"] * (1 - aliquota_efetiva(d)),
                               soma(d["patrimonio_liquido"], divida_liquida(d)))),

    # ---------------- Fluxo de caixa (Seção 2.6) ----------------
    Indicador("fco_lucro", "FCO / Lucro líquido (qualidade do lucro)", "Fluxo de caixa", "x",
              "Caixa das atividades operacionais ÷ Lucro líquido", "complementar",
              lambda d, m: div(d["fco"], d["lucro_liquido"])),
    Indicador("fluxo_livre_aprox", "Fluxo de caixa livre (aprox.)", "Fluxo de caixa", "R$",
              "Caixa operacional + Caixa de investimento", "Seção 2.6",
              lambda d, m: soma(d["fco"], d["fci"])),
    Indicador("payout", "Índice de payout", "Fluxo de caixa", "%",
              "Dividendos (e JCP) pagos ÷ Lucro líquido", "Eq. 2.21",
              lambda d, m: div(abs(d["dividendos_pagos"]) if not pd.isna(d["dividendos_pagos"]) else np.nan,
                               d["lucro_liquido"])),

    # ---------------- Avaliação de mercado (Seções 2.3 e 2.5) ----------------
    Indicador("valor_mercado", "Capitalização de mercado", "Avaliação de mercado", "R$",
              "Preço da ação × Nº de ações", "Seção 2.2",
              lambda d, m: m["valor_mercado"], usa_mercado=True),
    Indicador("market_to_book", "Market-to-book", "Avaliação de mercado", "x",
              "Capitalização de mercado ÷ PL contábil", "Eq. 2.3",
              lambda d, m: div(m["valor_mercado"], d["patrimonio_liquido"]), usa_mercado=True),
    Indicador("valor_empresa", "Valor da empresa (EV)", "Avaliação de mercado", "R$",
              "Capitalização + Dívida − Caixa", "Eq. 2.5",
              lambda d, m: m["valor_mercado"] + divida_liquida(d), usa_mercado=True),
    Indicador("preco_lucro", "Preço / Lucro (P/L)", "Avaliação de mercado", "x",
              "Capitalização de mercado ÷ Lucro líquido", "Eq. 2.19",
              lambda d, m: div(m["valor_mercado"], d["lucro_liquido"]), usa_mercado=True),
    Indicador("ev_ebitda", "EV / EBITDA", "Avaliação de mercado", "x",
              "Valor da empresa ÷ EBITDA", "Seção 2.5",
              lambda d, m: div(m["valor_mercado"] + divida_liquida(d), ebitda(d)), usa_mercado=True),
]

# Dicionário de acesso rápido: chave -> Indicador
POR_CHAVE = {ind.chave: ind for ind in INDICADORES}


# ---------------------------------------------------------------------------
# Cálculos principais
# ---------------------------------------------------------------------------

def calcular_indicadores(df, mercado=None):
    """
    Calcula todos os indicadores para todos os anos do DataFrame.

    Os índices de mercado só são calculados para o ANO MAIS RECENTE, pois a
    cotação capturada é a atual (não faria sentido dividir o valor de
    mercado de hoje pelo lucro de anos atrás).

    Retorna DataFrame: linhas = chaves dos indicadores, colunas = anos.
    """
    anos = list(df.columns)
    resultado = {}
    for ind in INDICADORES:
        if ind.usa_mercado and not mercado:
            continue  # sem dados de mercado, pula a categoria de avaliação
        linha = {}
        for ano in anos:
            if ind.usa_mercado and ano != anos[-1]:
                linha[ano] = np.nan
                continue
            try:
                linha[ano] = ind.calcular(df[ano], mercado)
            except (KeyError, TypeError):
                linha[ano] = np.nan  # conta ausente -> indicador indisponível
        resultado[ind.chave] = linha
    return pd.DataFrame(resultado).T[anos]


def verificar_balanco(df):
    """
    Verifica a identidade fundamental do balanço (Eq. 2.1):
        Ativo = Passivo + Patrimônio Líquido
    Retorna Series com a diferença percentual em cada ano (deve ser ~0).
    """
    return (df.loc["ativo_total"] - df.loc["passivo_total"]) / df.loc["ativo_total"]


def analise_vertical(df):
    """
    Análise vertical: expressa cada conta como percentual de uma base.
        - contas do balanço  -> % do Ativo Total
        - contas da DRE      -> % da Receita Líquida
    """
    from captura import MAPA_CONTAS
    linhas = {}
    for conta, (dem, _, _) in MAPA_CONTAS.items():
        base = df.loc["ativo_total"] if dem in ("BPA", "BPP") else df.loc["receita"] if dem == "DRE" else None
        if base is None:
            continue  # DFC não entra na análise vertical
        linhas[conta] = df.loc[conta] / base
    return pd.DataFrame(linhas).T


def analise_horizontal(df):
    """
    Análise horizontal: variação percentual de cada conta em relação ao ano
    anterior. A primeira coluna fica vazia (não há ano anterior).
    Usa o valor absoluto do denominador para que a variação tenha o sinal
    correto mesmo em contas negativas (custos, despesas).
    """
    anterior = df.shift(1, axis=1)
    return (df - anterior) / anterior.abs()


def dupont(df):
    """
    Decomposição DuPont do ROE (Eq. 2.18):
        ROE = Margem líquida × Giro dos ativos × Multiplicador do PL
    Retorna DataFrame com os três componentes e o ROE resultante.
    """
    ml = df.loc["lucro_liquido"] / df.loc["receita"]
    ga = df.loc["receita"] / df.loc["ativo_total"]
    mp = df.loc["ativo_total"] / df.loc["patrimonio_liquido"]
    return pd.DataFrame({"margem_liquida": ml, "giro_ativos": ga,
                         "multiplicador_pl": mp, "roe": ml * ga * mp}).T


# ---------------------------------------------------------------------------
# Diagnóstico automático
# ---------------------------------------------------------------------------

def diagnostico(df, ind, mercado=None):
    """
    Gera comentários interpretativos a partir de regras simples.
    Retorna lista de tuplas (nível, texto), onde nível é
    'ok', 'atencao', 'alerta' ou 'info'.

    IMPORTANTE: os limites usados são referências didáticas genéricas.
    Na prática, índices devem ser comparados com empresas do mesmo setor
    e com a própria série histórica da empresa.
    """
    msgs = []
    anos = list(df.columns)
    a = anos[-1]                                 # ano mais recente
    p = anos[-2] if len(anos) > 1 else None      # ano anterior (se houver)

    def v(chave, ano=a):
        """Valor de um indicador em um ano (NaN se não existir)."""
        return ind.at[chave, ano] if chave in ind.index and ano is not None else np.nan

    # 1) Consistência dos dados (Eq. 2.1)
    dif = verificar_balanco(df)
    if dif.isna().any():  # sem ativo total ou passivo total não há como verificar
        msgs.append(("atencao", "Não foi possível verificar a identidade Ativo = Passivo + PL (Eq. 2.1) "
                                "em todos os anos: faltam o ativo total ou o passivo total."))
    elif (dif.abs() > 0.005).any():
        msgs.append(("alerta", "A identidade Ativo = Passivo + PL (Eq. 2.1) não fecha em algum ano; "
                               "revise os dados de entrada."))
    else:
        msgs.append(("ok", "Identidade do balanço (Ativo = Passivo + PL, Eq. 2.1) verificada em todos os anos."))

    # 2) Crescimento da receita
    if p is not None and not pd.isna(df.at["receita", p]):
        cresc = df.at["receita", a] / df.at["receita", p] - 1
        msgs.append(("info", f"A receita variou {cresc:+.1%} em {a} em relação a {p}."))

    # 3) Liquidez
    lc, ls = v("liquidez_corrente"), v("liquidez_seca")
    if not pd.isna(lc):
        if lc < 1:
            msgs.append(("alerta", f"Liquidez corrente de {lc:.2f}x: o ativo circulante não cobre as "
                                   f"obrigações de curto prazo (capital de giro líquido negativo)."))
        elif lc < 1.2:
            msgs.append(("atencao", f"Liquidez corrente de {lc:.2f}x: folga pequena para honrar o curto prazo."))
        else:
            msgs.append(("ok", f"Liquidez corrente de {lc:.2f}x indica folga para honrar o curto prazo."))
        if not pd.isna(ls) and ls < 1 <= lc:
            msgs.append(("atencao", f"Sem os estoques, a liquidez cai para {ls:.2f}x (liquidez seca): "
                                    f"a cobertura do curto prazo depende da venda dos estoques."))

    # 4) Endividamento e capacidade de pagamento
    dl_ebitda, cob = v("divida_liquida_ebitda"), v("cobertura_juros")
    if not pd.isna(v("divida_liquida")) and v("divida_liquida") < 0:
        msgs.append(("ok", "A empresa possui caixa líquido (caixa e aplicações superam a dívida financeira)."))
    elif not pd.isna(dl_ebitda):
        if dl_ebitda > 3:
            msgs.append(("alerta", f"Dívida líquida/EBITDA de {dl_ebitda:.2f}x: endividamento elevado "
                                   f"em relação à geração operacional de caixa."))
        elif dl_ebitda > 2:
            msgs.append(("atencao", f"Dívida líquida/EBITDA de {dl_ebitda:.2f}x: endividamento moderado."))
        else:
            msgs.append(("ok", f"Dívida líquida/EBITDA de {dl_ebitda:.2f}x: endividamento confortável."))
    if not pd.isna(cob):
        nivel = "alerta" if cob < 1.5 else "atencao" if cob < 3 else "ok"
        msgs.append((nivel, f"O EBIT cobre {cob:.2f}x as despesas financeiras (cobertura de juros)."))

    # 5) Rentabilidade e DuPont
    ml = v("margem_liquida")
    if not pd.isna(ml) and ml < 0:
        msgs.append(("alerta", f"Margem líquida negativa ({ml:.1%}): a empresa teve prejuízo em {a}."))
    if p is not None:
        dp = dupont(df)
        roe_a, roe_p = dp.at["roe", a], dp.at["roe", p]
        if not (pd.isna(roe_a) or pd.isna(roe_p)):
            # Variação relativa de cada componente; o de maior módulo é o "motor" da mudança
            nomes = {"margem_liquida": "margem líquida", "giro_ativos": "giro dos ativos",
                     "multiplicador_pl": "alavancagem (multiplicador do PL)"}
            var = {k: dp.at[k, a] / dp.at[k, p] - 1 for k in nomes}
            motor = max(var, key=lambda k: abs(var[k]) if not pd.isna(var[k]) else -1)
            sentido = "subiu" if roe_a > roe_p else "caiu"
            msgs.append(("info", f"O ROE {sentido} de {roe_p:.1%} para {roe_a:.1%}. Pela análise DuPont "
                                 f"(Eq. 2.18), o componente que mais variou foi a {nomes[motor]} "
                                 f"({var[motor]:+.1%})."))

    # 6) Capital de giro
    if p is not None and not pd.isna(v("ciclo_caixa")) and not pd.isna(v("ciclo_caixa", p)):
        delta = v("ciclo_caixa") - v("ciclo_caixa", p)
        if abs(delta) >= 5:
            efeito = "mais" if delta > 0 else "menos"
            msgs.append(("atencao" if delta > 0 else "ok",
                         f"O ciclo de caixa {'aumentou' if delta > 0 else 'diminuiu'} {abs(delta):.0f} dias "
                         f"({v('ciclo_caixa', p):.0f} → {v('ciclo_caixa'):.0f}): a operação passou a exigir "
                         f"{efeito} capital de giro."))

    # 7) Qualidade do lucro (conversão em caixa)
    fco, q = df.at["fco", a], v("fco_lucro")
    if not pd.isna(fco) and fco < 0:
        msgs.append(("alerta", "O caixa das atividades operacionais foi negativo no último ano."))
    elif not pd.isna(q) and df.at["lucro_liquido", a] > 0:
        if q < 0.8:
            msgs.append(("atencao", f"Apenas {q:.0%} do lucro líquido virou caixa operacional: o lucro pode "
                                    f"estar 'preso' em capital de giro (recebíveis, estoques)."))
        else:
            msgs.append(("ok", f"O caixa operacional equivale a {q:.2f}x o lucro líquido: boa conversão do lucro em caixa."))

    # 8) Avaliação de mercado (se disponível)
    if mercado:
        pl, mtb = v("preco_lucro"), v("market_to_book")
        if not pd.isna(pl) and not pd.isna(mtb):
            msgs.append(("info", f"Com o valor de mercado atual, a ação negocia a {pl:.1f}x o lucro de {a} (P/L) "
                                 f"e a {mtb:.2f}x o patrimônio contábil (market-to-book)."))

    # Converte o separador decimal dos números para o padrão brasileiro (1.94 -> 1,94)
    return [(nivel, re.sub(r"(?<!Eq\. )(\d)\.(\d)", r"\1,\2", texto)) for nivel, texto in msgs]
