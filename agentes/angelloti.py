import os
from datetime import date
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY"))


def criterios_graham(ind: dict) -> dict:
    p_l = ind.get("p_l") or 0
    p_vp = ind.get("p_vp") or 0
    roe = ind.get("roe") or 0
    net_margin = ind.get("net_margin") or 0

    criterios = {
        "p_l_baixo": p_l > 0 and p_l < 15,
        "p_vp_baixo": p_vp > 0 and p_vp < 1.5,
        "roe_positivo": roe > 0.10,
        "margem_positiva": net_margin > 0,
    }
    aprovados = sum(criterios.values())
    score = round((aprovados / len(criterios)) * 100)
    return {"criterios": criterios, "score": score}


def criterios_bazin(ind: dict) -> dict:
    dy = ind.get("dividend_yield") or 0
    p_l = ind.get("p_l") or 0

    criterios = {
        "dy_acima_6pct": dy >= 6.0,
        "p_l_razoavel": 0 < p_l < 20,
        "lucro_positivo": (ind.get("net_margin") or 0) > 0,
    }
    aprovados = sum(criterios.values())
    score = round((aprovados / len(criterios)) * 100)
    return {"criterios": criterios, "score": score}


def criterios_lynch(ind: dict) -> dict:
    p_l = ind.get("p_l") or 0
    roe = ind.get("roe") or 0

    criterios = {
        "p_l_crescimento": 0 < p_l < 30,
        "roe_solido": roe > 0.15,
        "margem_positiva": (ind.get("net_margin") or 0) > 0,
    }
    aprovados = sum(criterios.values())
    score = round((aprovados / len(criterios)) * 100)
    return {"criterios": criterios, "score": score}


def criterios_housel(ind: dict) -> dict:
    dy = ind.get("dividend_yield") or 0
    p_vp = ind.get("p_vp") or 0

    criterios = {
        "dividend_consistente": dy > 0,
        "valuation_justo": 0 < p_vp < 3,
        "margem_positiva": (ind.get("net_margin") or 0) > 0,
    }
    aprovados = sum(criterios.values())
    score = round((aprovados / len(criterios)) * 100)
    return {"criterios": criterios, "score": score}


def gerar_recomendacao(scores: dict) -> str:
    media = sum(scores.values()) / len(scores)
    if media >= 75:
        return "compra"
    elif media >= 50:
        return "manter"
    else:
        return "evitar"


def processar_todos():
    print("=== Agente Angelloti iniciado ===")
    hoje = date.today().isoformat()

    resp = supabase.table("indicators").select("*").eq("date", hoje).execute()
    indicators = resp.data

    if not indicators:
        print("Nenhum indicador encontrado para hoje. Rode o coletor primeiro.")
        return

    print(f"Processando {len(indicators)} ativos...")
    scores_batch = []

    for ind in indicators:
        ticker = ind["ticker"]

        graham = criterios_graham(ind)
        bazin = criterios_bazin(ind)
        lynch = criterios_lynch(ind)
        housel = criterios_housel(ind)

        scores = {
            "graham": graham["score"],
            "bazin": bazin["score"],
            "lynch": lynch["score"],
            "housel": housel["score"],
        }

        overall = round(sum(scores.values()) / len(scores))
        recomendacao = gerar_recomendacao(scores)

        scores_batch.append({
            "ticker": ticker,
            "date": hoje,
            "score_graham": graham["score"],
            "score_bazin": bazin["score"],
            "score_lynch": lynch["score"],
            "score_housel": housel["score"],
            "overall_score": overall,
            "recommendation": recomendacao,
            "criteria": {
                "graham": graham["criterios"],
                "bazin": bazin["criterios"],
                "lynch": lynch["criterios"],
                "housel": housel["criterios"],
            },
        })

    supabase.table("angelloti_scores").upsert(scores_batch, on_conflict="ticker,date").execute()
    print(f"=== Angelloti concluído: {len(scores_batch)} ativos analisados ===")

    top = sorted(scores_batch, key=lambda x: x["overall_score"], reverse=True)[:10]
    print("\nTop 10 por score geral:")
    for a in top:
        print(f"  {a['ticker']}: {a['overall_score']}% — {a['recommendation']}")


if __name__ == "__main__":
    processar_todos()
