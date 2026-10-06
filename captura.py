"""
captura.py
==========
Módulo de CAPTURA DE DADOS da aplicação.

A aplicação aceita três fontes de dados:

1. CVM (Comissão de Valores Mobiliários) - Dados Abertos
   Baixa automaticamente as Demonstrações Financeiras Padronizadas (DFP)
   publicadas por todas as companhias abertas brasileiras em
   https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/
   Cada arquivo anual (.zip) contém vários CSVs, um por demonstração:
       BPA -> Balanço Patrimonial Ativo
       BPP -> Balanço Patrimonial Passivo (inclui o Patrimônio Líquido)
       DRE -> Demonstração do Resultado do Exercício
       DFC -> Demonstração dos Fluxos de Caixa (método indireto "MI" ou direto "MD")

2. Arquivo CSV local
   Permite analisar qualquer empresa (inclusive de capital fechado) a partir
   de uma planilha no formato padrão da aplicação (ver dados/modelo_empresa.csv).

3. Dados de mercado (opcional)
   Cotação e número de ações via biblioteca "yfinance", ou valor de mercado
   informado manualmente. São usados nos índices de avaliação do Cap. 2
   (market-to-book, valor da empresa, P/L, EV/EBITDA).

Em todos os casos o resultado é um DataFrame "padronizado":
    - linhas  = contas padronizadas (chaves da tabela MAPA_CONTAS abaixo)
    - colunas = anos (exercícios sociais)
    - valores em R$ (reais), mantendo a convenção de sinais da CVM:
      custos, despesas, IR e saídas de caixa aparecem NEGATIVOS.
"""

import unicodedata
import zipfile
from pathlib import Path

import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

# Endereço dos arquivos anuais da DFP. "{ano}" é substituído pelo exercício.
URL_DFP = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_{ano}.zip"

# Pasta onde os .zip baixados ficam guardados, para não baixar de novo
# em execuções futuras (cada arquivo tem dezenas de MB).
PASTA_CACHE = Path(__file__).resolve().parent / "cache"

# Mapeamento entre as contas usadas na análise e os códigos do plano de
# contas padronizado da CVM para empresas NÃO financeiras.
# Formato: chave_padronizada -> (demonstração, código da conta, descrição)
MAPA_CONTAS = {
    # ----- Balanço Patrimonial: Ativo (BPA) -----
    "ativo_total":            ("BPA", "1",       "Ativo Total"),
    "ativo_circulante":       ("BPA", "1.01",    "Ativo Circulante"),
    "caixa":                  ("BPA", "1.01.01", "Caixa e Equivalentes de Caixa"),
    "aplicacoes_financeiras": ("BPA", "1.01.02", "Aplicações Financeiras (CP)"),
    "contas_receber":         ("BPA", "1.01.03", "Contas a Receber"),
    "estoques":               ("BPA", "1.01.04", "Estoques"),
    "ativo_nao_circulante":   ("BPA", "1.02",    "Ativo Não Circulante"),
    "imobilizado":            ("BPA", "1.02.03", "Imobilizado (ativos fixos)"),
    # ----- Balanço Patrimonial: Passivo e PL (BPP) -----
    "passivo_total":          ("BPP", "2",       "Passivo Total (Passivo + PL)"),
    "passivo_circulante":     ("BPP", "2.01",    "Passivo Circulante"),
    "fornecedores":           ("BPP", "2.01.02", "Fornecedores (contas a pagar)"),
    "emprestimos_cp":         ("BPP", "2.01.04", "Empréstimos e Financiamentos (CP)"),
    "passivo_nao_circulante": ("BPP", "2.02",    "Passivo Não Circulante"),
    "emprestimos_lp":         ("BPP", "2.02.01", "Empréstimos e Financiamentos (LP)"),
    "patrimonio_liquido":     ("BPP", "2.03",    "Patrimônio Líquido"),
    # ----- Demonstração do Resultado (DRE) -----
    "receita":                ("DRE", "3.01",    "Receita Líquida de Vendas"),
    "custo":                  ("DRE", "3.02",    "Custo dos Bens/Serviços Vendidos"),
    "lucro_bruto":            ("DRE", "3.03",    "Resultado Bruto"),
    "ebit":                   ("DRE", "3.05",    "EBIT (resultado antes do res. financeiro e tributos)"),
    "receitas_financeiras":   ("DRE", "3.06.01", "Receitas Financeiras"),
    "despesas_financeiras":   ("DRE", "3.06.02", "Despesas Financeiras"),
    "lucro_antes_ir":         ("DRE", "3.07",    "Resultado Antes dos Tributos (LAIR)"),
    "ir_csll":                ("DRE", "3.08",    "IR e CSLL"),
    "lucro_liquido":          ("DRE", "3.11",    "Lucro/Prejuízo do Período"),
    # ----- Demonstração dos Fluxos de Caixa (DFC) -----
    "fco":                    ("DFC", "6.01",    "Caixa Líquido das Atividades Operacionais"),
    "fci":                    ("DFC", "6.02",    "Caixa Líquido das Atividades de Investimento"),
    "fcf":                    ("DFC", "6.03",    "Caixa Líquido das Atividades de Financiamento"),
}

# Contas que NÃO têm código fixo no plano da CVM (cada empresa abre a sua
# subconta com descrição própria). São obtidas por palavra-chave na DFC.
CONTAS_EXTRAS = {
    "depreciacao":      ("DFC", "Depreciação e Amortização (ajuste na DFC)"),
    "dividendos_pagos": ("DFC", "Dividendos e JCP Pagos"),
}

# Lista completa de contas padronizadas, na ordem em que aparecem nos relatórios.
CONTAS_PADRAO = list(MAPA_CONTAS) + list(CONTAS_EXTRAS)

# Descrição legível de cada conta (usada nos relatórios).
DESCRICAO_CONTAS = {k: v[2] for k, v in MAPA_CONTAS.items()}
DESCRICAO_CONTAS.update({k: v[1] for k, v in CONTAS_EXTRAS.items()})


# ---------------------------------------------------------------------------
# Funções auxiliares
# ---------------------------------------------------------------------------

def _sem_acento(texto):
    """Remove acentos e converte para minúsculas (facilita buscas por nome)."""
    texto = unicodedata.normalize("NFKD", str(texto))
    return "".join(c for c in texto if not unicodedata.combining(c)).lower()


def baixar_dfp(ano):
    """
    Baixa (ou reaproveita do cache) o arquivo .zip da DFP de um ano.

    Retorna o caminho do arquivo local, ou None se o arquivo não existir
    no site da CVM (por exemplo, um ano cujas demonstrações ainda não foram
    publicadas).
    """
    PASTA_CACHE.mkdir(exist_ok=True)
    destino = PASTA_CACHE / f"dfp_cia_aberta_{ano}.zip"

    # Se já foi baixado antes, não baixa de novo.
    if destino.exists() and destino.stat().st_size > 0:
        print(f"  [cache] DFP {ano} já disponível localmente.")
        return destino

    url = URL_DFP.format(ano=ano)
    print(f"  Baixando DFP {ano} da CVM: {url}")

    def _fazer_download(verificar_ssl):
        # stream=True baixa o arquivo em blocos, sem carregar tudo na memória
        with requests.get(url, stream=True, timeout=180, verify=verificar_ssl) as resp:
            if resp.status_code == 404:
                return False
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))
            baixado = 0
            temporario = destino.with_suffix(".part")
            with open(temporario, "wb") as arq:
                for bloco in resp.iter_content(chunk_size=1 << 20):  # blocos de 1 MB
                    arq.write(bloco)
                    baixado += len(bloco)
                    if total:  # barra de progresso simples no terminal
                        print(f"\r    {baixado / 1e6:6.1f} MB ({baixado / total:5.1%})", end="")
            print()
            # Só renomeia ao final: um download interrompido não vira cache "corrompido".
            temporario.rename(destino)
            return True

    try:
        ok = _fazer_download(verificar_ssl=True)
    except requests.exceptions.SSLError:
        # O portal de dados abertos já apresentou problemas na cadeia de
        # certificados em alguns ambientes. Como os dados são públicos e
        # apenas lidos (nada é enviado), tentamos novamente sem verificação.
        print("  Aviso: falha na verificação SSL do portal da CVM; tentando novamente sem verificação.")
        requests.packages.urllib3.disable_warnings()
        ok = _fazer_download(verificar_ssl=False)

    if not ok:
        print(f"  DFP {ano} não encontrada no portal da CVM (ano ainda não publicado?).")
        return None
    return destino


def _ler_csv_do_zip(caminho_zip, trecho_nome):
    """
    Lê, de dentro do .zip, o CSV cujo nome contém `trecho_nome`
    (ex.: '_BPA_con_'). Os arquivos da CVM usam ';' como separador
    e codificação latin-1. Tudo é lido como texto e convertido depois.
    """
    with zipfile.ZipFile(caminho_zip) as z:
        nomes = [n for n in z.namelist() if trecho_nome in n]
        if not nomes:
            return pd.DataFrame()
        with z.open(nomes[0]) as arq:
            return pd.read_csv(arq, sep=";", encoding="latin-1", dtype=str)


def _filtrar_empresa(df, cd_cvm):
    """
    Mantém apenas as linhas da empresa desejada, do exercício mais recente
    do arquivo (ORDEM_EXERC = 'ÚLTIMO') e da versão mais recente do documento
    (empresas podem reapresentar a DFP, gerando versões 2, 3, ...).
    Também converte VL_CONTA para número em reais, aplicando a escala
    ('MIL' significa que os valores estão em milhares de reais).
    """
    if df.empty:
        return df
    df = df[pd.to_numeric(df["CD_CVM"], errors="coerce") == int(cd_cvm)].copy()
    if df.empty:
        return df
    # 'ÚLTIMO' = exercício de referência; 'PENÚLTIMO' = exercício anterior (comparativo)
    df = df[~df["ORDEM_EXERC"].str.upper().str.contains("PEN")]
    df["VERSAO"] = pd.to_numeric(df["VERSAO"], errors="coerce")
    df = df[df["VERSAO"] == df["VERSAO"].max()]
    escala = df["ESCALA_MOEDA"].str.upper().map({"MIL": 1000.0}).fillna(1.0)
    df["VALOR"] = pd.to_numeric(df["VL_CONTA"], errors="coerce") * escala
    return df


def _valor_conta(df, codigo):
    """Retorna o valor da conta com o código exato informado (ou NaN se não existir)."""
    linhas = df[df["CD_CONTA"] == codigo]
    return float(linhas["VALOR"].iloc[0]) if not linhas.empty else float("nan")


def _soma_por_palavra(df, prefixo_codigo, palavras):
    """
    Soma as contas cujo código começa com `prefixo_codigo` e cuja descrição
    contém alguma das `palavras`. Usado para itens sem código fixo na CVM
    (depreciação, dividendos pagos). Considera apenas o nível imediatamente
    abaixo do prefixo para não somar a mesma conta duas vezes (pai + filhas).
    """
    nivel = prefixo_codigo.count(".") + 1
    sel = df[df["CD_CONTA"].str.startswith(prefixo_codigo + ".")
             & (df["CD_CONTA"].str.count(r"\.") == nivel)]
    desc = sel["DS_CONTA"].map(_sem_acento)
    mascara = desc.apply(lambda d: any(p in d for p in palavras))
    return float(sel.loc[mascara, "VALOR"].sum()) if mascara.any() else float("nan")


# ---------------------------------------------------------------------------
# Fonte 1: CVM
# ---------------------------------------------------------------------------

def buscar_empresas(termo, ano):
    """
    Procura companhias abertas cujo nome contenha `termo` (sem diferenciar
    maiúsculas/acentos) na DFP do `ano`. Retorna DataFrame com
    CD_CVM, DENOM_CIA e CNPJ_CIA, para o usuário escolher a empresa certa.
    """
    caminho = baixar_dfp(ano)
    if caminho is None:
        return pd.DataFrame()
    dre = _ler_csv_do_zip(caminho, f"_DRE_con_{ano}")
    if dre.empty:
        dre = _ler_csv_do_zip(caminho, f"_DRE_ind_{ano}")
    empresas = dre[["CD_CVM", "DENOM_CIA", "CNPJ_CIA"]].drop_duplicates("CD_CVM")
    termo = _sem_acento(termo)
    achadas = empresas[empresas["DENOM_CIA"].map(_sem_acento).str.contains(termo, regex=False)]
    return achadas.reset_index(drop=True)


def capturar_cvm(cd_cvm, anos):
    """
    Monta o DataFrame padronizado de uma empresa a partir das DFPs da CVM.

    Parâmetros
    ----------
    cd_cvm : int   código da empresa na CVM (ex.: 5410 = WEG)
    anos   : list  exercícios desejados (ex.: [2022, 2023, 2024, 2025])

    Retorna
    -------
    (DataFrame padronizado, dicionário de metadados)
    """
    dados = {}
    meta = {"fonte": "CVM - Dados Abertos (DFP)", "cd_cvm": int(cd_cvm),
            "nome": None, "cnpj": None, "tipo_demonstracao": None}

    for ano in sorted(anos):
        caminho = baixar_dfp(ano)
        if caminho is None:
            continue

        # Preferimos as demonstrações CONSOLIDADAS ("con"), que incluem as
        # controladas. Se a empresa não tiver controladas, só existem as
        # INDIVIDUAIS ("ind").
        for tipo in ("con", "ind"):
            bpa = _filtrar_empresa(_ler_csv_do_zip(caminho, f"_BPA_{tipo}_{ano}"), cd_cvm)
            if not bpa.empty:
                break
        if bpa.empty:
            print(f"  Empresa {cd_cvm} sem DFP em {ano}.")
            continue

        bpp = _filtrar_empresa(_ler_csv_do_zip(caminho, f"_BPP_{tipo}_{ano}"), cd_cvm)
        dre = _filtrar_empresa(_ler_csv_do_zip(caminho, f"_DRE_{tipo}_{ano}"), cd_cvm)
        # A DFC pode estar no método indireto (MI, mais comum) ou direto (MD).
        dfc = _filtrar_empresa(_ler_csv_do_zip(caminho, f"_DFC_MI_{tipo}_{ano}"), cd_cvm)
        if dfc.empty:
            dfc = _filtrar_empresa(_ler_csv_do_zip(caminho, f"_DFC_MD_{tipo}_{ano}"), cd_cvm)

        # Instituições financeiras usam outro plano de contas: nelas a conta
        # 1.01 não é o "Ativo Circulante" (nos bancos é "Caixa e Equivalentes").
        # Os códigos de MAPA_CONTAS apontariam para contas erradas e o relatório
        # sairia sem sentido, por isso a análise é interrompida.
        desc_101 = bpa.loc[bpa["CD_CONTA"] == "1.01", "DS_CONTA"]
        if desc_101.empty or "circulante" not in _sem_acento(desc_101.iloc[0]):
            raise ValueError(f"{bpa['DENOM_CIA'].iloc[0]} usa o plano de contas de instituição "
                             "financeira (banco/seguradora), que esta aplicação não suporta.")

        tabelas = {"BPA": bpa, "BPP": bpp, "DRE": dre, "DFC": dfc}

        # Contas com código fixo
        valores = {chave: _valor_conta(tabelas[dem], cod)
                   for chave, (dem, cod, _) in MAPA_CONTAS.items()}

        # Contas obtidas por palavra-chave (sinais conforme a CVM)
        valores["depreciacao"] = _soma_por_palavra(dfc, "6.01.01", ["deprecia", "amortiza", "exaust"])
        valores["dividendos_pagos"] = _soma_por_palavra(dfc, "6.03", ["dividendo", "juros sobre capital",
                                                                      "juros sobre o capital"])
        dados[ano] = valores

        # Metadados (nome e CNPJ vêm do próprio arquivo)
        meta["nome"] = bpa["DENOM_CIA"].iloc[0]
        meta["cnpj"] = bpa["CNPJ_CIA"].iloc[0]
        meta["tipo_demonstracao"] = "Consolidada" if tipo == "con" else "Individual"

    if not dados:
        raise ValueError("Nenhum dado encontrado para a empresa/anos informados.")

    df = pd.DataFrame(dados).reindex(CONTAS_PADRAO)
    return df, meta


# ---------------------------------------------------------------------------
# Fonte 2: CSV local
# ---------------------------------------------------------------------------

def capturar_csv(caminho, nome=None):
    """
    Lê um CSV no formato padrão da aplicação:

        conta,2022,2023,2024
        receita,1200000,1380000,1450000
        custo,-780000,-910000,-980000
        ...

    - a primeira coluna ("conta") usa as chaves de CONTAS_PADRAO;
    - as demais colunas são os anos; valores em reais, ponto como decimal;
    - o separador (',' ou ';') é detectado automaticamente;
    - linhas iniciadas por '#' são comentários e são ignoradas.
    """
    caminho = Path(caminho)
    df = pd.read_csv(caminho, sep=None, engine="python", comment="#")
    df = df.set_index(df.columns[0])
    df.index = df.index.str.strip()
    df.columns = [int(str(c).strip()) for c in df.columns]
    df = df.apply(pd.to_numeric, errors="coerce")

    desconhecidas = [c for c in df.index if c not in CONTAS_PADRAO]
    if desconhecidas:
        print(f"  Aviso: contas ignoradas (não reconhecidas): {desconhecidas}")
    faltando = [c for c in CONTAS_PADRAO if c not in df.index]
    if faltando:
        print(f"  Aviso: contas ausentes no arquivo (índices dependentes ficarão vazios): {faltando}")

    df = df.reindex(CONTAS_PADRAO)[sorted(df.columns)]
    # Um arquivo sem nenhum valor (ex.: o modelo em branco) geraria um relatório vazio
    if df.isna().all().all():
        raise ValueError(f"o arquivo {caminho.name} não tem valores preenchidos "
                         "(preencha os valores de cada conta e ano).")
    meta = {"fonte": f"Arquivo local: {caminho.name}",
            "nome": nome or caminho.stem.replace("_", " ").title(),
            "cnpj": None, "cd_cvm": None, "tipo_demonstracao": "Conforme arquivo"}
    return df, meta


# ---------------------------------------------------------------------------
# Fonte 3: dados de mercado (opcional)
# ---------------------------------------------------------------------------

def capturar_mercado(ticker=None, valor_mercado_manual=None):
    """
    Obtém o valor de mercado (capitalização) da empresa.

    - Se `valor_mercado_manual` for informado, usa esse valor diretamente.
    - Senão, se `ticker` for informado (ex.: 'WEGE3'), consulta a cotação
      atual via yfinance (biblioteca opcional; requer internet).

    Retorna dicionário com os dados ou None se não for possível obter.
    Observação: a cotação é ATUAL, por isso os índices de avaliação são
    calculados apenas para o exercício mais recente.
    """
    if valor_mercado_manual:
        return {"fonte": "informado pelo usuário", "valor_mercado": float(valor_mercado_manual),
                "ticker": ticker, "preco": None, "acoes": None}
    if not ticker:
        return None
    try:
        import yfinance as yf  # importado aqui pois é opcional
    except ImportError:
        print("  Aviso: 'yfinance' não instalado; índices de mercado serão omitidos "
              "(pip install yfinance).")
        return None

    simbolo = ticker.upper() if ticker.upper().endswith(".SA") else ticker.upper() + ".SA"
    try:
        info = yf.Ticker(simbolo).fast_info
        preco = float(info["last_price"])
        valor = float(info["market_cap"])          # capitalização = preço x nº de ações
        acoes = valor / preco if preco else None
        return {"fonte": f"Yahoo Finance ({simbolo})", "ticker": simbolo,
                "preco": preco, "acoes": acoes, "valor_mercado": valor}
    except Exception as erro:  # rede indisponível, ticker inválido etc.
        print(f"  Aviso: não foi possível obter dados de mercado de {simbolo}: {erro}")
        return None
