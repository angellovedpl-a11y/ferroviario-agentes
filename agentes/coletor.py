import os
import requests
import yfinance as yf
import pandas as pd
from datetime import date
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

BRAPI_TOKEN = os.getenv("BRAPI_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

BRAPI_BASE = "https://brapi.dev/api"


def buscar_todos_tickers() -> list[str]:
    print("Buscando lista de tickers da B3...")
    resp = requests.get(f"{BRAPI_BASE}/quote/list?token={BRAPI_TOKEN}", timeout=30)
    resp.raise_for_status()
    stocks = resp.json().get("stocks", [])

    tickers = []
    for s in stocks:
        t = s.get("stock", "")
        if not t:
            continue
        # Exclui BDRs (terminam em 2 dígitos tipo 34, 35: AAPL34, GOOGL34)
        # Mantém "11" pois é sufixo de FIIs e ETFs (HGLG11, BOVA11)
        if t[-2:].isdigit() and t[-2:] != "11":
            continue
        # Exclui mercado fracionário (mesmo ativo do lote padrão, lote de 1-99)
        if t.endswith("F"):
            continue
        if len(t) >= 4 and t[:4].isalpha():
            tickers.append(t)

    print(f"  {len(tickers)} ativos brasileiros filtrados")
    return tickers


def buscar_cotacoes(tickers: list[str]) -> list[dict]:
    print(f"Buscando dados via yfinance ({len(tickers)} ativos)...")
    hoje = date.today().isoformat()
    yf_tickers = [f"{t}.SA" for t in tickers]

    # Baixa histórico de preços de todos de uma vez (1 requisição)
    print("  Baixando histórico de preços (5 dias)...")
    try:
        raw = yf.download(
            yf_tickers,
            period="5d",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as e:
        print(f"  Erro no download de preços: {e}")
        raw = pd.DataFrame()

    resultados = []
    total = len(tickers)

    for i, (ticker, yf_ticker) in enumerate(zip(tickers, yf_tickers)):
        if i % 100 == 0 and i > 0:
            print(f"  Progresso: {i}/{total}")

        # Extrai preço e variação do batch download
        price = change_pct = None
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                closes = raw["Close"][yf_ticker].dropna()
            else:
                closes = raw["Close"].dropna()

            if len(closes) >= 1:
                price = float(closes.iloc[-1])
            if len(closes) >= 2:
                prev = float(closes.iloc[-2])
                change_pct = (price - prev) / prev * 100 if prev else None
        except (KeyError, TypeError):
            pass

        # Fundamentais e volume via .info
        info = {}
        try:
            info = yf.Ticker(yf_ticker).info or {}
        except Exception:
            pass

        if price is None:
            price = info.get("regularMarketPrice") or info.get("currentPrice")

        resultados.append({
            "ticker": ticker,
            "name": info.get("longName") or info.get("shortName", ""),
            "sector": info.get("sector", ""),
            "type": "fii" if ticker.endswith("11") else "stock",
            "price": price,
            "change_pct": change_pct,
            "volume": info.get("regularMarketVolume") or info.get("volume"),
            "p_l": info.get("trailingPE"),
            "p_vp": info.get("priceToBook"),
            "dividend_yield": info.get("dividendYield"),
            "roe": info.get("returnOnEquity"),
            "net_margin": info.get("profitMargins"),
            "date": hoje,
        })

    print(f"  {len(resultados)} ativos processados")
    return resultados


def salvar_assets(dados: list[dict]):
    print("Salvando cadastro de ativos...")
    assets = [
        {
            "ticker": d["ticker"],
            "name": d["name"],
            "sector": d["sector"],
            "type": d["type"],
        }
        for d in dados if d["ticker"]
    ]
    supabase.table("assets").upsert(assets, on_conflict="ticker").execute()
    print(f"  {len(assets)} ativos salvos")


def salvar_prices(dados: list[dict]):
    print("Salvando preços...")
    prices = [
        {
            "ticker": d["ticker"],
            "date": d["date"],
            "price": d["price"],
            "change_pct": d["change_pct"],
            "volume": d["volume"],
        }
        for d in dados if d["price"] is not None
    ]
    supabase.table("prices").upsert(prices, on_conflict="ticker,date").execute()
    print(f"  {len(prices)} preços salvos")


def salvar_indicators(dados: list[dict]):
    print("Salvando indicadores...")
    indicators = [
        {
            "ticker": d["ticker"],
            "date": d["date"],
            "p_l": d["p_l"],
            "p_vp": d["p_vp"],
            "dividend_yield": d["dividend_yield"],
            "roe": d["roe"],
            "net_margin": d["net_margin"],
            "source": "yfinance",
        }
        for d in dados
    ]
    supabase.table("indicators").upsert(indicators, on_conflict="ticker,date").execute()
    print(f"  {len(indicators)} indicadores salvos")


def main():
    print("=== Agente Coletor iniciado ===")
    tickers = buscar_todos_tickers()
    dados = buscar_cotacoes(tickers)

    if not dados:
        print("Nenhum dado coletado. Encerrando.")
        return

    salvar_assets(dados)
    salvar_prices(dados)
    salvar_indicators(dados)
    print(f"=== Coleta concluída: {len(dados)} ativos processados ===")


if __name__ == "__main__":
    main()
