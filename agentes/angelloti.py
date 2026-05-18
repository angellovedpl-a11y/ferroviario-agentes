"""
Agente Angelloti — screening quantitativo para a comunidade Ferroviário Investidor.

ATENÇÃO (auditoria 2026-05-18):

- Os critérios "Graham/Bazin/Lynch" são REDUÇÕES SIMPLIFICADAS dos métodos canônicos.
  Faltam séries históricas (10+ anos), Número de Graham, preço-teto Bazin, PEG Lynch.
  Para análise fundamentalista completa é obrigatório usar fonte primária (CVM/B3) e
  revisão por analista CNPI.

- Os scores são SCREENING QUANTITATIVO. NÃO constituem recomendação de investimento
  conforme Resolução CVM 20/2021. O ranking não considera suitability (Res. CVM 30/2021).

- O campo "recommendation" (compra/manter/evitar) foi SUBSTITUÍDO por "screening_tier"
  (A/B/C/D/N-A) + "screening_label" descritivo — rótulo não-imperativo para evitar
  caracterização de recomendação automatizada.

- Cada critério é acompanhado por um comentário analítico explicando POR QUE foi
  atendido ou não, com base nos valores observados.

- FIIs, ETFs e ações têm pipelines distintos. ETFs não recebem score.

- O critério "Housel" original foi removido. Morgan Housel não possui framework
  quantitativo de stock picking; atribuir métricas a ele contradiz a tese do autor.
  Foi substituído por "qualidade_conservadora".
"""

import os
from datetime import date
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY"))

METHODOLOGY_VERSION = "2.2.0"


# ---------- Helpers ----------

def num_or_none(val):
    """Coerção para float que preserva ausência. Use quando 'ausente' não equivale a 'zero'."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


# ---------- Comentários analíticos por métrica ----------

def _comentario_pl(p_l, teto: float) -> str:
    if p_l is None:
        return "P/L não disponível na fonte de dados — critério inconclusivo."
    if p_l <= 0:
        return f"P/L = {p_l:.2f} (não positivo). Empresa com prejuízo ou caso atípico contábil; o método exige lucros consistentes."
    if p_l < teto:
        return f"P/L = {p_l:.2f}, abaixo do teto de {teto:g} — múltiplo conservador, mercado não paga prêmio elevado sobre os lucros."
    return f"P/L = {p_l:.2f}, acima do teto de {teto:g} — mercado precifica expectativa; o método exigiria desconto maior."


def _comentario_pvp(p_vp, teto: float) -> str:
    if p_vp is None:
        return "P/VP não disponível na fonte — critério inconclusivo."
    if p_vp <= 0:
        return f"P/VP = {p_vp:.2f} — patrimônio líquido negativo ou anomalia contábil; sinal de alerta."
    if p_vp < teto:
        return f"P/VP = {p_vp:.2f}, abaixo de {teto:g} — ação cotada com prêmio contido sobre o valor patrimonial."
    return f"P/VP = {p_vp:.2f}, acima de {teto:g} — mercado paga prêmio relevante sobre o patrimônio; o método exigiria valuation mais ajustado."


def _comentario_roe(roe, piso: float) -> str:
    if roe is None:
        return "ROE não disponível — critério inconclusivo."
    pct = roe * 100
    piso_pct = piso * 100
    if roe > piso:
        return f"ROE = {pct:.1f}%, acima do piso de {piso_pct:.0f}% — empresa rentabiliza bem o capital próprio."
    return f"ROE = {pct:.1f}%, abaixo do piso de {piso_pct:.0f}% — eficiência abaixo do esperado pelo método; verifique se é setor capital-intensivo ou ciclo ruim."


def _comentario_dy_piso(dy, piso: float) -> str:
    if dy is None:
        return "Dividend Yield não disponível — critério inconclusivo."
    pct = dy * 100
    piso_pct = piso * 100
    if dy >= piso:
        return f"DY = {pct:.2f}%, acima do piso de {piso_pct:.0f}% — ativo paga dividendos relevantes em relação à cotação atual."
    if dy > 0:
        return f"DY = {pct:.2f}%, abaixo do piso de {piso_pct:.0f}% — distribui dividendo, mas em magnitude insuficiente para o método."
    return f"DY = {pct:.2f}% — ativo não distribui dividendos no período."


def _comentario_paga_dividendo(dy) -> str:
    if dy is None:
        return "DY não disponível — critério inconclusivo."
    pct = dy * 100
    if dy > 0:
        return f"DY = {pct:.2f}% — ativo distribui dividendos, sinal de geração de caixa real."
    return "Ativo não distribui dividendos no período — perfil sem renda passiva."


def _comentario_margem(margem) -> str:
    if margem is None:
        return "Margem líquida não disponível — critério inconclusivo."
    pct = margem * 100
    if margem > 0:
        return f"Margem líquida = {pct:.1f}% — empresa converte receita em lucro."
    return f"Margem líquida = {pct:.1f}% — empresa não dá lucro no período; sinal vermelho para qualquer método fundamentalista."


# ---------- Critérios para AÇÕES ----------

def criterios_graham(ind: dict) -> dict:
    """Graham simplificado. Faltam: 10 anos sem prejuízo, dividendos 20+ anos,
    liquidez corrente > 2, Número de Graham (P/L × P/VP < 22.5), porte da empresa."""
    p_l = num_or_none(ind.get("p_l"))
    p_vp = num_or_none(ind.get("p_vp"))
    roe = num_or_none(ind.get("roe"))
    margem = num_or_none(ind.get("net_margin"))

    criterios = {
        "p_l_baixo": p_l is not None and 0 < p_l < 15,
        "p_vp_baixo": p_vp is not None and 0 < p_vp < 1.5,
        "roe_solido": roe is not None and roe > 0.10,
        "margem_positiva": margem is not None and margem > 0,
    }
    comentarios = {
        "p_l_baixo": _comentario_pl(p_l, 15),
        "p_vp_baixo": _comentario_pvp(p_vp, 1.5),
        "roe_solido": _comentario_roe(roe, 0.10),
        "margem_positiva": _comentario_margem(margem),
    }
    score = round((sum(criterios.values()) / len(criterios)) * 100)
    return {"criterios": criterios, "comentarios": comentarios, "score": score}


def criterios_bazin(ind: dict) -> dict:
    """Bazin simplificado. Falta: preço-teto via dividendos médios de 5 anos,
    consistência histórica de DPA, crescimento de dividendos."""
    dy = num_or_none(ind.get("dividend_yield"))  # yfinance: decimal (0.06 = 6%)
    p_l = num_or_none(ind.get("p_l"))
    margem = num_or_none(ind.get("net_margin"))

    criterios = {
        "dy_acima_6pct": dy is not None and dy >= 0.06,
        "p_l_razoavel": p_l is not None and 0 < p_l < 20,
        "lucro_positivo": margem is not None and margem > 0,
    }
    comentarios = {
        "dy_acima_6pct": _comentario_dy_piso(dy, 0.06),
        "p_l_razoavel": _comentario_pl(p_l, 20),
        "lucro_positivo": _comentario_margem(margem),
    }
    score = round((sum(criterios.values()) / len(criterios)) * 100)
    return {"criterios": criterios, "comentarios": comentarios, "score": score}


def criterios_lynch(ind: dict) -> dict:
    """Lynch simplificado. Falta: PEG (P/L ÷ crescimento), categorização do tipo de
    empresa (slow grower / stalwart / fast grower / cyclical), nível de endividamento."""
    p_l = num_or_none(ind.get("p_l"))
    roe = num_or_none(ind.get("roe"))
    margem = num_or_none(ind.get("net_margin"))

    criterios = {
        "p_l_crescimento": p_l is not None and 0 < p_l < 30,
        "roe_solido": roe is not None and roe > 0.15,
        "margem_positiva": margem is not None and margem > 0,
    }
    comentarios = {
        "p_l_crescimento": _comentario_pl(p_l, 30),
        "roe_solido": _comentario_roe(roe, 0.15),
        "margem_positiva": _comentario_margem(margem),
    }
    score = round((sum(criterios.values()) / len(criterios)) * 100)
    return {"criterios": criterios, "comentarios": comentarios, "score": score}


def criterios_qualidade_conservadora(ind: dict) -> dict:
    """Heurística defensiva — paga dividendo, valuation contido, dá lucro.
    NÃO é metodologia de Morgan Housel (Housel não tem framework quantitativo)."""
    dy = num_or_none(ind.get("dividend_yield"))
    p_vp = num_or_none(ind.get("p_vp"))
    margem = num_or_none(ind.get("net_margin"))

    criterios = {
        "paga_dividendo": dy is not None and dy > 0,
        "valuation_contido": p_vp is not None and 0 < p_vp < 3,
        "margem_positiva": margem is not None and margem > 0,
    }
    comentarios = {
        "paga_dividendo": _comentario_paga_dividendo(dy),
        "valuation_contido": _comentario_pvp(p_vp, 3),
        "margem_positiva": _comentario_margem(margem),
    }
    score = round((sum(criterios.values()) / len(criterios)) * 100)
    return {"criterios": criterios, "comentarios": comentarios, "score": score}


# ---------- Critérios para FIIs ----------

def criterios_fii(ind: dict) -> dict:
    """Screening básico de FII. Faltam: vacância, cap rate, segmento, gestora,
    histórico de distribuição (não disponíveis via yfinance)."""
    dy = num_or_none(ind.get("dividend_yield"))
    p_vp = num_or_none(ind.get("p_vp"))

    criterios = {
        "dy_acima_6pct": dy is not None and dy >= 0.06,
        "p_vp_proximo_um": p_vp is not None and 0 < p_vp < 1.1,
        "p_vp_descontado": p_vp is not None and 0 < p_vp < 1.0,
    }
    comentarios = {
        "dy_acima_6pct": _comentario_dy_piso(dy, 0.06),
        "p_vp_proximo_um": _comentario_pvp(p_vp, 1.1),
        "p_vp_descontado": _comentario_pvp(p_vp, 1.0),
    }
    score = round((sum(criterios.values()) / len(criterios)) * 100)
    return {"criterios": criterios, "comentarios": comentarios, "score": score}


# ---------- Classificação descritiva (Opção 2) ----------

TIER_LABELS = {
    "A": "Proposição de estudo aprofundado — múltiplos critérios atendidos",
    "B": "Proposição de estudo — atendimento parcial relevante",
    "C": "Fundamentos a investigar — critérios pendentes",
    "D": "Fundamentos críticos a investigar — múltiplos critérios pendentes",
    "N-A": "Não aplicável a este tipo de ativo",
}


def classificar_tier(media_score) -> dict:
    """Tier descritivo não-imperativo. Retorna code + label legível."""
    if media_score is None:
        code = "N-A"
    elif media_score >= 75:
        code = "A"
    elif media_score >= 60:
        code = "B"
    elif media_score >= 40:
        code = "C"
    else:
        code = "D"
    return {"code": code, "label": TIER_LABELS[code]}


def carregar_tipos_ativos() -> dict:
    """Mapa ticker → tipo (stock/fii/etf) a partir da tabela assets."""
    resp = supabase.table("assets").select("ticker,type").execute()
    return {a["ticker"]: (a.get("type") or "stock") for a in resp.data}


def calcular_required_profile(asset_type: str, overall_score) -> str:
    """Perfil mínimo recomendado para acompanhar o ativo no screening.

    Heurística inicial (sem dados de volatilidade/beta na base atual):
      - ETF                                 → conservador
      - FII com score >= 67 (2/3 critérios) → conservador
      - FII com score < 67                  → moderado
      - Ação com overall_score >= 60 (A/B)  → moderado
      - Ação com overall_score < 60 (C/D)   → arrojado
      - Ativo sem score (None)              → moderado (fallback)
    """
    if asset_type == "etf":
        return "conservador"
    if asset_type == "fii":
        if overall_score is not None and overall_score >= 67:
            return "conservador"
        return "moderado"
    # stock
    if overall_score is None:
        return "moderado"
    if overall_score >= 60:
        return "moderado"
    return "arrojado"


# ---------- Pipelines por tipo de ativo ----------

def processar_acao(ind: dict) -> dict:
    graham = criterios_graham(ind)
    bazin = criterios_bazin(ind)
    lynch = criterios_lynch(ind)
    qualidade = criterios_qualidade_conservadora(ind)

    overall = round((graham["score"] + bazin["score"] + lynch["score"] + qualidade["score"]) / 4)
    tier = classificar_tier(overall)

    return {
        "score_graham": graham["score"],
        "score_bazin": bazin["score"],
        "score_lynch": lynch["score"],
        "score_qualidade": qualidade["score"],
        "overall_score": overall,
        "screening_tier": tier["code"],
        "screening_label": tier["label"],
        "criteria": {
            "graham": {"criterios": graham["criterios"], "comentarios": graham["comentarios"]},
            "bazin": {"criterios": bazin["criterios"], "comentarios": bazin["comentarios"]},
            "lynch": {"criterios": lynch["criterios"], "comentarios": lynch["comentarios"]},
            "qualidade_conservadora": {"criterios": qualidade["criterios"], "comentarios": qualidade["comentarios"]},
        },
    }


def processar_fii(ind: dict) -> dict:
    fii = criterios_fii(ind)
    tier = classificar_tier(fii["score"])
    return {
        "score_graham": None,
        "score_bazin": None,
        "score_lynch": None,
        "score_qualidade": fii["score"],
        "overall_score": fii["score"],
        "screening_tier": tier["code"],
        "screening_label": tier["label"],
        "criteria": {
            "fii": {"criterios": fii["criterios"], "comentarios": fii["comentarios"]},
        },
    }


def processar_etf(ind: dict) -> dict:
    tier = classificar_tier(None)
    return {
        "score_graham": None,
        "score_bazin": None,
        "score_lynch": None,
        "score_qualidade": None,
        "overall_score": None,
        "screening_tier": tier["code"],
        "screening_label": tier["label"],
        "criteria": {
            "observacao": "ETFs não são avaliados por critérios fundamentalistas neste agente. Análise apropriada considera índice de referência, tracking error, taxa de administração, liquidez e composição."
        },
    }


# ---------- Orquestração ----------

def processar_todos():
    print("=== Agente Angelloti iniciado ===")
    print(f"Metodologia: v{METHODOLOGY_VERSION}")
    print("AVISO: screening quantitativo — não constitui recomendação de investimento (Res. CVM 20/2021).")

    hoje = date.today().isoformat()
    tipos = carregar_tipos_ativos()

    resp = supabase.table("indicators").select("*").eq("date", hoje).execute()
    indicators = resp.data

    if not indicators:
        print("Nenhum indicador encontrado para hoje. Rode o coletor primeiro.")
        return

    print(f"Processando {len(indicators)} ativos...")
    scores_batch = []

    for ind in indicators:
        ticker = ind["ticker"]
        tipo = tipos.get(ticker, "stock")

        if tipo == "fii":
            resultado = processar_fii(ind)
        elif tipo == "etf":
            resultado = processar_etf(ind)
        else:
            resultado = processar_acao(ind)

        resultado["required_profile"] = calcular_required_profile(tipo, resultado["overall_score"])

        scores_batch.append({
            "ticker": ticker,
            "date": hoje,
            "asset_type": tipo,
            "methodology_version": METHODOLOGY_VERSION,
            **resultado,
        })

    supabase.table("angelloti_scores").upsert(scores_batch, on_conflict="ticker,date").execute()
    print(f"=== Angelloti concluído: {len(scores_batch)} ativos analisados ===")

    avaliados = [a for a in scores_batch if a["overall_score"] is not None]
    top = sorted(avaliados, key=lambda x: x["overall_score"], reverse=True)[:10]
    print("\nTop 10 por overall_score (screening — NÃO é recomendação):")
    for a in top:
        print(f"  {a['ticker']} ({a['asset_type']}): {a['overall_score']}% — tier {a['screening_tier']}")
        print(f"      {a['screening_label']}")


if __name__ == "__main__":
    processar_todos()
