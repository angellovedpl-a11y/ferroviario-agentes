import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from urllib.parse import quote

import requests
import yfinance as yf
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

BRAPI_TOKEN = os.getenv("BRAPI_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

SI_BASE = "https://statusinvest.com.br"
SI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}

# Setores no Status Invest (numeração interna da API, descoberta empiricamente).
# Total observado: ~557 ações ativas. Setores 2 e 4 batem em 100 (limite duro da
# API) — pode ter cauda longa que cairia em fragmentação por subsetor.
SECTOR_NAMES: dict[int, str] = {
    1: "Bens Industriais",
    2: "Consumo Cíclico",
    3: "Consumo não Cíclico",
    4: "Financeiro",
    5: "Materiais Básicos",
    6: "Petróleo, Gás e Biocombustíveis",
    7: "Saúde",
    8: "Tecnologia da Informação",
    9: "Comunicações",
    10: "Utilidade Pública",
}

BRAPI_BASE = "https://brapi.dev/api"


# ---------- Status Invest ----------

def si_advanced_search(category_type: int, sector: int | None = None) -> list[dict]:
    """Busca fundamentos consolidados via endpoint público do Status Invest."""
    search = {"Sector": str(sector), "SubSector": "", "Segment": ""} if sector else {}
    url = f"{SI_BASE}/category/advancedsearchresult?CategoryType={category_type}&search={quote(json.dumps(search))}"
    referer = f"{SI_BASE}/{'acoes' if category_type == 1 else 'fundos-imobiliarios'}/busca-avancada"
    resp = requests.post(url, headers={**SI_HEADERS, "Referer": referer}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        return []
    return [r for r in data if r.get("ticker")]


def si_dy(ticker: str) -> float | None:
    """Dividend yield 12m via indicatorhistoricallist (chave `dy`, campo `actual`).

    O endpoint /acao/companytickerprovents retorna `rendiment`, mas esse é a
    variação YoY do rendimento de proventos — não o DY 12m. Para o DY clássico,
    usamos o indicatorhistoricallist que tem o histórico completo por indicador.
    """
    try:
        resp = requests.post(
            f"{SI_BASE}/acao/indicatorhistoricallist",
            headers={**SI_HEADERS, "Referer": f"{SI_BASE}/acoes/{ticker.lower()}"},
            data={"codes": ticker, "time": 7, "byQuarter": "false", "futureData": "false"},
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        data = (resp.json() or {}).get("data") or {}
        if not data:
            return None
        # A chave vem como camelCase do ticker (ex: "petR4"); pegamos o primeiro valor.
        indicators = next(iter(data.values()), None)
        if not indicators:
            return None
        dy_row = next((x for x in indicators if x.get("key") == "dy"), None)
        return float(dy_row["actual"]) if dy_row and dy_row.get("actual") is not None else None
    except Exception:
        return None


def coletar_stocks_e_fiis() -> list[dict]:
    """Stocks (10 setores) + FIIs via Status Invest, com DY paralelizado."""
    coletados: dict[str, dict] = {}

    print("Status Invest > stocks por setor")
    for sec, sec_name in SECTOR_NAMES.items():
        try:
            rows = si_advanced_search(1, sector=sec)
            for r in rows:
                r["_asset_type"] = "stock"
                r["_sector"] = sec_name
                coletados[r["ticker"]] = r
            print(f"  {sec_name}: {len(rows)} ações")
        except Exception as e:
            print(f"  {sec_name}: erro {e}")
        time.sleep(0.5)

    print("Status Invest > FIIs")
    try:
        rows = si_advanced_search(2)
        for r in rows:
            r["_asset_type"] = "fii"
            r["_sector"] = "Fundo Imobiliário"
            coletados[r["ticker"]] = r
        print(f"  {len(rows)} FIIs")
    except Exception as e:
        print(f"  FII: erro {e}")
    time.sleep(0.5)

    print(f"Status Invest > dividend yield ({len(coletados)} ativos, 5 workers)")
    tickers = list(coletados.keys())

    def fetch_dy(t: str) -> tuple[str, float | None]:
        return t, si_dy(t)

    with ThreadPoolExecutor(max_workers=5) as ex:
        for i, fut in enumerate(as_completed([ex.submit(fetch_dy, t) for t in tickers]), 1):
            t, dy = fut.result()
            coletados[t]["_dy"] = dy
            if i % 100 == 0:
                print(f"  DY: {i}/{len(tickers)}")

    return list(coletados.values())


# ---------- yfinance (BDRs apenas) ----------

def coletar_bdrs_yfinance() -> list[dict]:
    """BDRs: o Status Invest não tem endpoint público de busca; mantém yfinance."""
    print("BRAPI > listando tickers para identificar BDRs")
    try:
        resp = requests.get(f"{BRAPI_BASE}/quote/list?token={BRAPI_TOKEN}", timeout=30)
        resp.raise_for_status()
        stocks = resp.json().get("stocks", [])
    except Exception as e:
        print(f"  erro BRAPI: {e}")
        return []

    bdrs = []
    for s in stocks:
        t = s.get("stock", "")
        if not t or t.endswith("F"):
            continue
        # BDR: termina em 2 dígitos diferentes de "11" (ex: AAPL34, GOOGL34)
        if t[-2:].isdigit() and t[-2:] != "11" and len(t) >= 4 and t[:4].isalpha():
            bdrs.append(t)

    print(f"  {len(bdrs)} BDRs candidatos")

    yf_tickers = [f"{t}.SA" for t in bdrs]
    resultados = []

    for i, (ticker, yf_ticker) in enumerate(zip(bdrs, yf_tickers)):
        if i % 50 == 0 and i > 0:
            print(f"  BDR: {i}/{len(bdrs)}")
        try:
            info = yf.Ticker(yf_ticker).info or {}
        except Exception:
            info = {}
        price = info.get("regularMarketPrice") or info.get("currentPrice")
        name = info.get("longName") or info.get("shortName")
        if not price or not name:
            continue
        resultados.append({
            "ticker": ticker,
            "name": name,
            "sector": info.get("sector", ""),
            "_asset_type": "bdr",
            "price": price,
            "p_l": info.get("trailingPE"),
            "p_vp": info.get("priceToBook"),
            "roe": _to_pct(info.get("returnOnEquity")),
            "margemliquida": _to_pct(info.get("profitMargins")),
            "_dy": _to_pct(info.get("dividendYield")),
        })

    print(f"  {len(resultados)} BDRs com dados válidos")
    return resultados


def _to_pct(v):
    """yfinance retorna decimais (0.15 = 15%). Convertemos para porcentagem."""
    if v is None:
        return None
    try:
        return float(v) * 100
    except (TypeError, ValueError):
        return None


# ---------- Normalização ----------

def normalizar(row: dict, hoje: str) -> dict:
    """Adapta payload bruto (Status Invest ou yfinance) ao schema das tabelas."""
    asset_type = row["_asset_type"]
    ticker = row["ticker"]

    return {
        "asset": {
            "ticker": ticker,
            "name": row.get("companyname") or row.get("name") or "",
            "sector": row.get("_sector") or row.get("sector") or "",
            "type": asset_type,
        },
        "price": {
            "ticker": ticker,
            "date": hoje,
            "price": _f(row.get("price")),
            "change_pct": None,  # Status Invest não retorna no bulk; pode vir depois
            "volume": None,
        },
        "indicators": {
            "ticker": ticker,
            "date": hoje,
            "source": "status_invest" if asset_type in ("stock", "fii") else "yfinance",
            "p_l": _f(row.get("p_l")),
            "p_vp": _f(row.get("p_vp")),
            "p_ebit": _f(row.get("p_ebit")),
            "ev_ebit": _f(row.get("ev_ebit")),
            "p_ativo": _f(row.get("p_ativo")),
            "p_sr": _f(row.get("p_sr")),
            "p_capitalgiro": _f(row.get("p_capitalgiro")),
            "p_ativocirculante": _f(row.get("p_ativocirculante")),
            "giro_ativos": _f(row.get("giroativos")),
            "roe": _f(row.get("roe")),
            "roa": _f(row.get("roa")),
            "roic": _f(row.get("roic")),
            "gross_margin": _f(row.get("margembruta")),
            "ebit_margin": _f(row.get("margemebit")),
            "net_margin": _f(row.get("margemliquida")),
            "divida_liquida_pl": _f(row.get("dividaliquidapatrimonioliquido")),
            "divida_liquida_ebit": _f(row.get("dividaliquidaebit")),
            "pl_ativo": _f(row.get("pl_ativo")),
            "passivo_ativo": _f(row.get("passivo_ativo")),
            "liquidez_corrente": _f(row.get("liquidezcorrente")),
            "liquidez_media_diaria": _f(row.get("liquidezmediadiaria")),
            "peg_ratio": _f(row.get("peg_ratio")),
            "cagr_receitas_5a": _f(row.get("receitas_cagr5")),
            "cagr_lucros_5a": _f(row.get("lucros_cagr5")),
            "vpa": _f(row.get("vpa")),
            "lpa": _f(row.get("lpa")),
            "valor_mercado": _f(row.get("valormercado")),
            "dividend_yield": _f(row.get("_dy")),
        },
    }


def _f(v):
    if v is None:
        return None
    try:
        x = float(v)
        return x if x == x else None  # NaN → None
    except (TypeError, ValueError):
        return None


# ---------- Persistência ----------

def salvar(normalizado: list[dict]):
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    print(f"Salvando {len(normalizado)} ativos no Supabase...")
    assets = [n["asset"] for n in normalizado if n["asset"]["ticker"]]
    prices = [n["price"] for n in normalizado if n["price"]["price"] is not None]
    indicators = [n["indicators"] for n in normalizado]

    supabase.table("assets").upsert(assets, on_conflict="ticker").execute()
    print(f"  assets: {len(assets)}")

    if prices:
        supabase.table("prices").upsert(prices, on_conflict="ticker,date").execute()
        print(f"  prices: {len(prices)}")

    supabase.table("indicators").upsert(indicators, on_conflict="ticker,date").execute()
    print(f"  indicators: {len(indicators)}")


def main():
    print("=== Coletor Ferroviário Investidor ===")
    hoje = date.today().isoformat()

    raw = []
    raw.extend(coletar_stocks_e_fiis())
    raw.extend(coletar_bdrs_yfinance())

    if not raw:
        print("Nada coletado. Encerrando.")
        return

    # Descarta o que não tem o mínimo: preço E nome.
    filtrados = [
        r for r in raw
        if (r.get("price") is not None) and (r.get("companyname") or r.get("name"))
    ]
    descartados = len(raw) - len(filtrados)
    print(f"Total bruto: {len(raw)} | válidos: {len(filtrados)} | descartados: {descartados}")

    normalizado = [normalizar(r, hoje) for r in filtrados]
    salvar(normalizado)

    print(f"=== Coleta concluída: {len(normalizado)} ativos ===")


if __name__ == "__main__":
    main()
