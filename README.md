# TP1 — Administração Financeira: Análise de Demonstrações Financeiras

- **Disciplina:** Administração Financeira (CAD 167) — UFMG, 2º semestre de 2026
- **Professor:** Bruno Pérez Ferreira
- **Autores:** Lucas Dolabella de Castro Lopes e Vanessa Nascimento Silva

Aplicação em Python que **captura** as demonstrações financeiras de uma empresa, **calcula** os índices do Capítulo 2 de Berk, DeMarzo & Harford (*Fundamentos de Finanças Empresariais*) e **gera relatórios** (terminal, HTML com gráficos e planilha Excel).

## Instalação

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Requer Python 3.9+. O pacote `yfinance` é opcional (só é usado com o ticker).

## Execução

### Interface web (recomendada)

```bash
streamlit run app.py
```

Abre no navegador uma página com formulário na barra lateral (CVM, upload de CSV ou exemplo), cartões com os principais índices, gráficos interativos, diagnóstico e botões para baixar o relatório HTML e a planilha Excel.

### Terminal

| Comando | O que faz |
|---|---|
| `python main.py` | Menu interativo |
| `python main.py --fonte exemplo` | Empresa fictícia; funciona **sem internet** |
| `python main.py --fonte cvm --empresa weg` | Busca a empresa pelo nome nos dados abertos da CVM |
| `python main.py --fonte cvm --cd-cvm 5410 --ticker WEGE3` | Código CVM + índices de mercado |
| `python main.py --fonte cvm --empresa ambev --anos 2021 2022 2023 2024` | Escolhe os exercícios |
| `python main.py --fonte csv --arquivo dados/modelo_empresa.csv --nome "Minha Empresa"` | Dados próprios em CSV |
| `python main.py --fonte exemplo --valor-mercado 1500000000` | Valor de mercado informado manualmente |

Na primeira execução com a CVM, cada ano baixa um arquivo de algumas dezenas de MB, guardado em `cache/` para as execuções seguintes. Os relatórios são salvos em `relatorios/`.

## Captura de dados

| Fonte | Origem | Observação |
|---|---|---|
| CVM | [Dados Abertos — DFP](https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/) | Todas as companhias abertas não financeiras; consolidado quando disponível |
| CSV | `dados/modelo_empresa.csv` | Qualquer empresa, inclusive de capital fechado |
| Mercado | Yahoo Finance (`--ticker`) ou `--valor-mercado` | Usado apenas nos índices de avaliação |

## Indicadores calculados

| Categoria | Indicadores | Referência (Berk, Cap. 2) |
|---|---|---|
| Liquidez | Capital de giro líquido, liquidez corrente, seca e imediata | Eq. 2.2, 2.6, 2.7 |
| Margens | Bruta, EBITDA, operacional, líquida | Eq. 2.9–2.11 |
| Eficiência | Giro dos ativos e dos ativos fixos, prazos médios, giro do estoque, ciclo de caixa | Eq. 2.12–2.15 |
| Alavancagem | Dívida bruta e líquida, dívida/PL, dívida líquida/EBITDA, cobertura de juros, multiplicador do PL | Eq. 2.4, Seção 2.5 |
| Retorno | ROE, ROA, ROIC e decomposição DuPont | Eq. 2.16–2.18 |
| Fluxo de caixa | FCO/lucro, fluxo de caixa livre aproximado, payout | Seção 2.6, Eq. 2.21 |
| Avaliação | Capitalização, market-to-book, EV, P/L, EV/EBITDA | Eq. 2.3, 2.5, 2.19 |

Também são geradas as análises **vertical** e **horizontal**, a verificação da identidade Ativo = Passivo + PL (Eq. 2.1) e um **diagnóstico textual** automático.

## Estrutura

```
app.py           # interface web (Streamlit)
main.py          # versão de terminal: argumentos, menu, orquestração
captura.py       # download e leitura da CVM, CSV local, dados de mercado
indicadores.py   # índices, análises vertical/horizontal, DuPont, diagnóstico
relatorio.py     # terminal, HTML com gráficos (matplotlib) e Excel
dados/           # empresa de exemplo (fictícia) e modelo de CSV
```

## Limitações

- Bancos e seguradoras usam plano de contas diferente e não são suportados.
- Arrendamentos (IFRS 16) não entram na dívida.
- Índices usam saldos de final de período, não médias.
- Índices de mercado usam a cotação atual e são calculados apenas para o último exercício.
