"""
main.py
=======
TP1 - Administração Financeira (CAD 167) - UFMG - 2º semestre de 2026
Professor: Bruno Pérez Ferreira
Autores: Lucas Dolabella de Castro Lopes e Vanessa Nascimento Silva
Tema: ANÁLISE DE DEMONSTRAÇÕES FINANCEIRAS

Aplicação que:
  1) CAPTURA as demonstrações financeiras de uma empresa (CVM, CSV ou exemplo);
  2) CALCULA os índices do Cap. 2 de Berk, DeMarzo & Harford (liquidez,
     margens, eficiência, alavancagem, retorno, DuPont, avaliação de mercado),
     além das análises vertical e horizontal;
  3) GERA RELATÓRIOS: resumo no terminal, relatório HTML com gráficos e
     planilha Excel com todas as tabelas.

Formas de execução
------------------
  python main.py                                   -> menu interativo
  python main.py --fonte exemplo                   -> dados fictícios (não precisa de internet)
  python main.py --fonte cvm --empresa "weg"       -> busca a empresa pelo nome na CVM
  python main.py --fonte cvm --cd-cvm 5410 --ticker WEGE3
  python main.py --fonte csv --arquivo dados/minha_empresa.csv --nome "Minha Empresa"

Use "python main.py --help" para ver todas as opções.
"""

import argparse
import sys
import webbrowser
from datetime import date, datetime
from pathlib import Path

import captura
import indicadores
import relatorio

PASTA_BASE = Path(__file__).resolve().parent
ARQUIVO_EXEMPLO = PASTA_BASE / "dados" / "exemplo_empresa.csv"

# Anos padrão: os 4 últimos exercícios encerrados. As DFPs de um ano são
# publicadas até março/abril do ano seguinte.
ULTIMO_ANO = date.today().year - 1
ANOS_PADRAO = list(range(ULTIMO_ANO - 3, ULTIMO_ANO + 1))


# ---------------------------------------------------------------------------
# Entrada de dados
# ---------------------------------------------------------------------------

def ler_argumentos():
    """Define e lê os argumentos de linha de comando."""
    p = argparse.ArgumentParser(description="Análise de demonstrações financeiras (TP1 - Adm. Financeira)")
    p.add_argument("--fonte", choices=["cvm", "csv", "exemplo"], help="origem dos dados")
    p.add_argument("--empresa", help="parte do nome da empresa para buscar na CVM (ex.: 'weg')")
    p.add_argument("--cd-cvm", type=int, help="código CVM da empresa (dispensa a busca por nome)")
    p.add_argument("--anos", type=int, nargs="+", default=ANOS_PADRAO,
                   help=f"exercícios a analisar (padrão: {' '.join(map(str, ANOS_PADRAO))})")
    p.add_argument("--arquivo", help="caminho do CSV (quando --fonte csv)")
    p.add_argument("--nome", help="nome da empresa exibido no relatório (fonte csv)")
    p.add_argument("--ticker", help="código de negociação na B3 para dados de mercado (ex.: WEGE3)")
    p.add_argument("--valor-mercado", type=float, help="valor de mercado em R$, informado manualmente")
    p.add_argument("--saida", default=str(PASTA_BASE / "relatorios"), help="pasta dos relatórios")
    p.add_argument("--nao-abrir", action="store_true", help="não abrir o relatório no navegador ao final")
    return p.parse_args()


def perguntar(texto, padrao=None):
    """Lê uma resposta do teclado, devolvendo `padrao` se o usuário só apertar Enter."""
    sufixo = f" [{padrao}]" if padrao is not None else ""
    resposta = input(f"{texto}{sufixo}: ").strip()
    return resposta or padrao


def menu_interativo(args):
    """Preenche os argumentos por meio de perguntas, quando o programa é
    executado sem parâmetros (ex.: duplo clique ou 'python main.py')."""
    print("\n=== Análise de Demonstrações Financeiras ===")
    print("Escolha a fonte dos dados:")
    print("  1 - CVM (dados oficiais de companhias abertas; requer internet)")
    print("  2 - Arquivo CSV próprio")
    print("  3 - Empresa de exemplo (dados fictícios, funciona offline)")
    # Repete a pergunta até receber uma opção válida
    fontes = {"1": "cvm", "2": "csv", "3": "exemplo"}
    while (opcao := perguntar("Opção", "1")) not in fontes:
        print("  Opção inválida: digite 1, 2 ou 3.")
    args.fonte = fontes[opcao]

    if args.fonte == "cvm":
        print("  (a base da CVM contém apenas companhias abertas brasileiras, ex.: weg, ambev, natura)")
        args.empresa = perguntar("Nome (ou parte do nome) da empresa", "weg")
        # Repete a pergunta até que todos os anos sejam números de 4 dígitos
        while True:
            anos = perguntar("Anos (separados por espaço)", " ".join(map(str, ANOS_PADRAO))).split()
            if anos and all(a.isdigit() and len(a) == 4 for a in anos):
                args.anos = [int(a) for a in anos]
                break
            print("  Anos inválidos: use números como 2023 2024.")
        args.ticker = perguntar("Ticker na B3 para índices de mercado (Enter para pular)", "") or None
    elif args.fonte == "csv":
        # Padrão: o CSV de exemplo (já preenchido). O modelo_empresa.csv vem em branco
        # e serve de ponto de partida para o usuário digitar os dados da sua empresa.
        print("  (para dados próprios, preencha uma cópia de dados/modelo_empresa.csv)")
        args.arquivo = perguntar("Caminho do arquivo CSV", str(PASTA_BASE / "dados" / "exemplo_empresa.csv"))
        args.nome = perguntar("Nome da empresa", None)
    return args


def escolher_empresa_cvm(args):
    """Resolve o código CVM: usa --cd-cvm ou busca pelo nome e, se houver
    mais de um resultado, pede ao usuário para escolher."""
    if args.cd_cvm:
        return args.cd_cvm
    if not args.empresa:
        sys.exit("Informe --empresa ou --cd-cvm para a fonte CVM.")
    print(f"\nBuscando '{args.empresa}' na base da CVM...")
    achadas = captura.buscar_empresas(args.empresa, max(args.anos))
    if achadas.empty:
        sys.exit("Nenhuma companhia encontrada com esse nome. Lembre que a CVM só tem companhias "
                 "abertas brasileiras\n(ex.: weg, ambev, natura, embraer; a Petrobras está como "
                 "'petroleo brasileiro').")
    if len(achadas) == 1:
        return int(achadas.at[0, "CD_CVM"])
    print("Mais de uma empresa encontrada:")
    for i, linha in achadas.iterrows():
        print(f"  {i + 1:>2} - {linha['DENOM_CIA']} (CVM {int(linha['CD_CVM'])}, CNPJ {linha['CNPJ_CIA']})")
    if not sys.stdin.isatty():  # execução não interativa: usa o primeiro resultado
        return int(achadas.at[0, "CD_CVM"])
    # Repete a pergunta até receber um número válido da lista
    while True:
        resposta = perguntar("Número da empresa", "1")
        if resposta.isdigit() and 1 <= int(resposta) <= len(achadas):
            return int(achadas.at[int(resposta) - 1, "CD_CVM"])
        print(f"  Opção inválida: digite um número de 1 a {len(achadas)}.")


# ---------------------------------------------------------------------------
# Programa principal
# ---------------------------------------------------------------------------

def main():
    """Executa as três etapas da aplicação: captura dos dados, cálculo dos
    indicadores e geração dos relatórios (terminal, HTML e Excel)."""
    args = ler_argumentos()
    if args.fonte is None:          # sem parâmetros -> menu interativo
        args = menu_interativo(args)

    # ---------- 1. CAPTURA ----------
    print("\n[1/3] Capturando dados...")
    try:
        if args.fonte == "cvm":
            df, meta = captura.capturar_cvm(escolher_empresa_cvm(args), args.anos)
        elif args.fonte == "csv":
            if not args.arquivo:
                sys.exit("Informe --arquivo para a fonte CSV.")
            df, meta = captura.capturar_csv(args.arquivo, args.nome)
        else:
            df, meta = captura.capturar_csv(ARQUIVO_EXEMPLO, "Empresa Exemplo S.A. (dados fictícios)")
    except Exception as erro:
        # Falhas de rede/portal não devem impedir a demonstração da aplicação
        print(f"\nErro na captura: {erro}")
        print("Dica: rode 'python main.py --fonte exemplo' para usar os dados de exemplo offline.")
        sys.exit(1)

    mercado = captura.capturar_mercado(args.ticker, args.valor_mercado)
    print(f"  {meta['nome']}: {len(df.columns)} exercício(s) capturado(s) -> {list(df.columns)}")

    # ---------- 2. CÁLCULO ----------
    print("[2/3] Calculando indicadores...")
    ind = indicadores.calcular_indicadores(df, mercado)
    diag = indicadores.diagnostico(df, ind, mercado)

    # ---------- 3. RELATÓRIOS ----------
    print("[3/3] Gerando relatórios...")
    pasta = Path(args.saida)
    pasta.mkdir(parents=True, exist_ok=True)
    # nome do arquivo sem acentos/espaços (ex.: "Empresa Exemplo S.A." -> "empresa_exemplo_s_a")
    nome_arquivo = "".join(c if c.isalnum() else "_" for c in captura._sem_acento(meta["nome"]))
    nome_arquivo = "_".join(p for p in nome_arquivo.split("_") if p)[:40]
    carimbo = datetime.now().strftime("%Y%m%d_%H%M%S")
    caminho_html = pasta / f"relatorio_{nome_arquivo}_{carimbo}.html"
    caminho_xlsx = pasta / f"relatorio_{nome_arquivo}_{carimbo}.xlsx"

    relatorio.imprimir_resumo(ind, diag, meta)
    relatorio.gerar_html(df, ind, diag, meta, mercado, caminho_html)
    relatorio.gerar_excel(df, ind, diag, caminho_xlsx)

    print(f"Relatório HTML : {caminho_html}")
    print(f"Planilha Excel : {caminho_xlsx}")
    if not args.nao_abrir:
        webbrowser.open(caminho_html.resolve().as_uri())


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):  # Ctrl+C / Ctrl+D durante as perguntas
        print("\nExecução cancelada pelo usuário.")
        sys.exit(130)
