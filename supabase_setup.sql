-- 1. Cadastro de ativos
CREATE TABLE IF NOT EXISTS assets (
  ticker TEXT PRIMARY KEY,
  name TEXT,
  sector TEXT,
  type TEXT DEFAULT 'stock',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Preços diários
CREATE TABLE IF NOT EXISTS prices (
  id BIGSERIAL PRIMARY KEY,
  ticker TEXT REFERENCES assets(ticker) ON DELETE CASCADE,
  date DATE NOT NULL,
  price NUMERIC,
  change_pct NUMERIC,
  volume BIGINT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(ticker, date)
);

-- 3. Indicadores fundamentalistas
CREATE TABLE IF NOT EXISTS indicators (
  id BIGSERIAL PRIMARY KEY,
  ticker TEXT REFERENCES assets(ticker) ON DELETE CASCADE,
  date DATE NOT NULL,
  p_l NUMERIC,
  p_vp NUMERIC,
  ev_ebitda NUMERIC,
  roe NUMERIC,
  roa NUMERIC,
  net_margin NUMERIC,
  dividend_yield NUMERIC,
  payout NUMERIC,
  debt_to_equity NUMERIC,
  net_debt_ebitda NUMERIC,
  revenue_growth NUMERIC,
  source TEXT DEFAULT 'brapi',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(ticker, date)
);

-- 4. Scores Angelloti
CREATE TABLE IF NOT EXISTS angelloti_scores (
  id BIGSERIAL PRIMARY KEY,
  ticker TEXT REFERENCES assets(ticker) ON DELETE CASCADE,
  date DATE NOT NULL,
  score_graham NUMERIC,
  score_bazin NUMERIC,
  score_lynch NUMERIC,
  score_housel NUMERIC,
  overall_score NUMERIC,
  recommendation TEXT,
  criteria JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(ticker, date)
);

-- Índices para performance
CREATE INDEX IF NOT EXISTS idx_prices_ticker_date ON prices(ticker, date DESC);
CREATE INDEX IF NOT EXISTS idx_indicators_ticker_date ON indicators(ticker, date DESC);
CREATE INDEX IF NOT EXISTS idx_angelloti_date ON angelloti_scores(date DESC);
CREATE INDEX IF NOT EXISTS idx_angelloti_score ON angelloti_scores(overall_score DESC);
