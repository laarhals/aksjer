#!/usr/bin/env python3
"""
Oslo Børs Portfolio Analyzer
Kjøres daglig via Claude Cowork eller cron-job.
Genererer en HTML-rapport som kan lastes opp til GitHub Pages.

Konfigurasjon leses fra portfolio.toml i samme mappe.
"""

import json
import os
import sys
import time
import datetime
import math
import random
from pathlib import Path

# Installer avhengigheter hvis de mangler
try:
    import yfinance as yf
    import pandas as pd
    import numpy as np
    import requests
except ImportError:
    os.system("pip install yfinance pandas numpy requests --break-system-packages -q")
    import yfinance as yf
    import pandas as pd
    import numpy as np
    import requests

# ============================================================
# LES KONFIGURASJON FRA portfolio.toml
# ============================================================

def _load_config():
    """
    Leser portfolio.toml fra samme mappe som scriptet.
    Faller tilbake på standardverdier hvis filen mangler.
    Python 3.11+ har innebygd tomllib. Eldre versjoner bruker tomli.
    """
    config_path = Path(__file__).parent / "portfolio.toml"

    if not config_path.exists():
        print(f"⚠️  portfolio.toml ikke funnet ({config_path})")
        print("   Bruker innebygde standardverdier.")
        return None

    # Last TOML-parser
    try:
        import tomllib                    # Python 3.11+
    except ImportError:
        try:
            import tomli as tomllib       # pip install tomli
        except ImportError:
            print("⚠️  Mangler TOML-parser. Installer med:")
            print("   pip install tomli")
            print("   (eller oppgrader til Python 3.11+)")
            return None

    with open(config_path, "rb") as f:
        cfg = tomllib.load(f)

    print(f"✅ Leste konfigurasjon fra {config_path.name}")
    return cfg


def _parse_portfolio(cfg):
    """Konverter [portfolio]-seksjonen til {ticker: aksjer}-dict."""
    if not cfg or "portfolio" not in cfg:
        return _default_portfolio()

    result = {}
    for ticker, val in cfg["portfolio"].items():
        if isinstance(val, dict):
            result[ticker] = int(val.get("shares", val.get("aksjer", 0)))
        elif isinstance(val, (int, float)):
            result[ticker] = int(val)
    return result if result else _default_portfolio()


def _default_portfolio():
    return {
        "EQNR.OL": 100, "DNB.OL": 150, "TEL.OL": 200,
        "MOWI.OL": 80,  "YAR.OL": 50,  "ORK.OL": 120,
        "SALM.OL": 40,  "SCATC.OL": 60, "AKER.OL": 30, "NHY.OL": 250,
    }


# Last konfigurasjon
_CFG = _load_config()

# Portefølje
MY_PORTFOLIO = _parse_portfolio(_CFG)

# Innstillinger
_SETTINGS    = (_CFG or {}).get("settings", {})
_SCORING     = (_CFG or {}).get("scoring", {})
_MINERVINI   = (_CFG or {}).get("minervini", {})

OUTPUT_FILE_NAME     = _SETTINGS.get("output_file", "index.html")
API_DELAY            = float(_SETTINGS.get("api_delay", 0.5))
SCREENER_MAX_TICKERS = int(_SETTINGS.get("screener_max_tickers", 0))
USE_PLAYWRIGHT       = bool(_SETTINGS.get("use_playwright", False))
USE_TICKER_CACHE     = bool(_SETTINGS.get("use_ticker_cache", True))
PORTFOLIO_NAME       = _SETTINGS.get("portfolio_name", "Min Oslo Børs-portefølje")

SCORE_POSITIVE       = float(_SCORING.get("score_positive", 7.0))
SCORE_NEUTRAL        = float(_SCORING.get("score_neutral", 5.0))
TECH_WEIGHT          = float(_SCORING.get("technical_weight", 0.5))
FUND_WEIGHT          = float(_SCORING.get("fundamental_weight", 0.5))

MIN_EPS_GROWTH       = float(_MINERVINI.get("min_eps_growth_pct", 20.0))
MIN_REV_GROWTH       = float(_MINERVINI.get("min_revenue_growth_pct", 15.0))
MIN_ROE              = float(_MINERVINI.get("min_roe_pct", 17.0))
MAX_PCT_FROM_HIGH    = float(_MINERVINI.get("max_pct_from_high", 25.0))
MIN_RS_RATING        = float(_MINERVINI.get("min_rs_rating", 70.0))

# Oslo Børs-tickers — hentes automatisk via fetch_tickers.py
OSEBX_TICKERS = []  # fylles dynamisk ved første kjøring

# Importer ticker-henter (faller tilbake på intern logikk hvis filen mangler)
try:
    from fetch_tickers import get_oslo_tickers as _get_oslo_tickers
    def fetch_oslo_bors_tickers(max_tickers=0, market="all"):
        tickers = _get_oslo_tickers(index=market, use_cache=True, verbose=True)
        return tickers[:max_tickers] if max_tickers else tickers
except ImportError:
    def fetch_oslo_bors_tickers(max_tickers=0, market="all"):
        print("  ⚠️  fetch_tickers.py ikke funnet — bruker intern fallback")
        return _builtin_fetch(max_tickers, market)

def _builtin_fetch(max_tickers=0, market="all"):
    """Intern fallback: scraper stockanalysis.com direkte."""
    import re
    try:
        resp = requests.get(
            "https://stockanalysis.com/list/oslo-bors/",
            headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"},
            timeout=20,
        )
        symbols = re.findall(r'/quote/osl/([A-Z0-9]{1,10})/', resp.text)
        seen, out = set(), []
        for s in symbols:
            t = s + ".OL"
            if t not in seen:
                seen.add(t); out.append(t)
        if out:
            print(f"  ✅ Intern scraper: {len(out)} aksjer")
            return out[:max_tickers] if max_tickers else out
    except Exception as e:
        print(f"  ⚠️  Intern scraper feilet: {e}")
    fallback = [
        "EQNR.OL","DNB.OL","KOG.OL","TEL.OL","AKERBP.OL","NHY.OL","YAR.OL",
        "GJF.OL","MOWI.OL","ORK.OL","VAR.OL","AKER.OL","SALM.OL","SUBC.OL",
        "STB.OL","FRO.OL","WAWI.OL","TOM.OL","NOD.OL","BAKKA.OL","LSG.OL",
        "VEI.OL","HAUTO.OL","ODL.OL","TGS.OL","KIT.OL","SCATC.OL","RECSI.OL",
        "PROT.OL","HAFNI.OL","DOFG.OL","MING.OL","SPOL.OL","SB1NO.OL",
        "SBNOR.OL","SRBANK.OL","TIETO.OL","AUTO.OL","CMBTO.OL","CRAYON.OL",
        "BOUVET.OL","ATEA.OL","SDRL.OL","PGS.OL","PARSG.OL","ARCH.OL",
    ]
    return fallback[:max_tickers] if max_tickers else fallback

OUTPUT_FILE = Path(__file__).parent / OUTPUT_FILE_NAME

# ============================================================
# TEKNISKE INDIKATORER
# ============================================================

def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = -delta.clip(upper=0).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def compute_macd(series, fast=12, slow=26, signal=9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

def compute_bollinger(series, period=20, std_dev=2):
    ma = series.rolling(period).mean()
    std = series.rolling(period).std()
    upper = ma + std_dev * std
    lower = ma - std_dev * std
    percent_b = (series - lower) / (upper - lower)
    return upper, lower, percent_b

def get_technical_indicators(ticker):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="2y")
        if hist.empty or len(hist) < 50:
            return None
        
        close = hist["Close"]
        high = hist["High"]
        low = hist["Low"]
        
        ma50 = close.rolling(50).mean().iloc[-1]
        ma200 = close.rolling(200).mean().iloc[-1]
        price = close.iloc[-1]
        
        rsi = compute_rsi(close).iloc[-1]
        macd_line, signal_line, histogram = compute_macd(close)
        
        upper_bb, lower_bb, pct_b = compute_bollinger(close)
        
        # ATR
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs()
        ], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().iloc[-1]
        atr_pct = (atr / price) * 100
        
        # 52-ukers posisjon
        high_52 = close.rolling(252).max().iloc[-1]
        low_52 = close.rolling(252).min().iloc[-1]
        pos_52w = ((price - low_52) / (high_52 - low_52)) * 100 if (high_52 - low_52) > 0 else 50
        
        # Avkastning
        ret_3m = ((price / close.iloc[-63]) - 1) * 100 if len(close) > 63 else None
        ret_12m = ((price / close.iloc[-252]) - 1) * 100 if len(close) > 252 else None
        
        # Gyllent kryss
        golden_cross = ma50 > ma200
        ma50_val = ma50
        ma200_val = ma200
        
        # Minervini kriterier
        ma150 = close.rolling(150).mean().iloc[-1]
        ma200_1m_ago = close.rolling(200).mean().iloc[-21] if len(close) > 221 else ma200 * 0.99
        ma200_trending_up = ma200 > ma200_1m_ago
        
        # Relativ styrke (vs referanse)
        high_52w = high_52
        within_25_of_high = price >= (high_52w * (1 - MAX_PCT_FROM_HIGH / 100))
        
        # RS-rating (enkel approksimering: 12m avkastning percentil)
        rs_approx = min(99, max(1, 50 + (ret_12m or 0) / 2))
        
        minervini = {
            "above_ma50": price > ma50,
            "above_ma150": price > ma150,
            "above_ma200": price > ma200,
            "ma50_above_ma150": ma50 > ma150,
            "ma150_above_ma200": ma150 > ma200,
            "ma200_trending_up": ma200_trending_up,
            "within_25_of_high": within_25_of_high,
            "rs_above_70": rs_approx > MIN_RS_RATING,
            "rs_rating": round(rs_approx, 1),
        }
        minervini["score"] = sum(1 for k, v in minervini.items() if isinstance(v, bool) and v)
        minervini["passes_all"] = minervini["score"] == 8
        
        # Teknisk anbefaling
        tech_score = 0
        if rsi < 30: tech_score += 2
        elif rsi > 70: tech_score -= 2
        elif 40 < rsi < 60: tech_score += 1
        if golden_cross: tech_score += 2
        if histogram.iloc[-1] > 0: tech_score += 1
        if pct_b.iloc[-1] < 0.2: tech_score += 1
        elif pct_b.iloc[-1] > 0.8: tech_score -= 1
        if (ret_3m or 0) > 5: tech_score += 1
        if (ret_12m or 0) > 10: tech_score += 1
        
        if tech_score >= 4: tech_rec = "KJØP"
        elif tech_score <= 0: tech_rec = "SELG"
        else: tech_rec = "HOLD"
        
        return {
            "price": round(price, 2),
            "rsi": round(rsi, 1),
            "ma50": round(ma50, 2),
            "ma200": round(ma200, 2),
            "ma150": round(ma150, 2),
            "golden_cross": golden_cross,
            "macd": round(macd_line.iloc[-1], 3),
            "macd_signal": round(signal_line.iloc[-1], 3),
            "macd_hist": round(histogram.iloc[-1], 3),
            "bb_pct_b": round(pct_b.iloc[-1], 3),
            "atr_pct": round(atr_pct, 2),
            "ret_3m": round(ret_3m, 1) if ret_3m else None,
            "ret_12m": round(ret_12m, 1) if ret_12m else None,
            "pos_52w": round(pos_52w, 1),
            "high_52w": round(high_52, 2),
            "low_52w": round(low_52, 2),
            "tech_recommendation": tech_rec,
            "tech_score": tech_score,
            "minervini": minervini,
        }
    except Exception as e:
        print(f"  Feil ved tekniske indikatorer for {ticker}: {e}")
        return None

# ============================================================
# FUNDAMENTALE INDIKATORER
# ============================================================

SECTOR_PROFILES = {
    "Energy": {"type": "syklisk", "pe_norm": 12, "eveb_norm": 8},
    "Financial Services": {"type": "verdi", "pe_norm": 11, "eveb_norm": 9},
    "Consumer Defensive": {"type": "verdi", "pe_norm": 18, "eveb_norm": 12},
    "Technology": {"type": "vekst", "pe_norm": 28, "eveb_norm": 20},
    "Healthcare": {"type": "vekst", "pe_norm": 22, "eveb_norm": 16},
    "Industrials": {"type": "syklisk", "pe_norm": 16, "eveb_norm": 11},
    "Basic Materials": {"type": "syklisk", "pe_norm": 14, "eveb_norm": 9},
    "Communication Services": {"type": "verdi", "pe_norm": 15, "eveb_norm": 10},
    "Consumer Cyclical": {"type": "syklisk", "pe_norm": 17, "eveb_norm": 12},
    "Real Estate": {"type": "verdi", "pe_norm": 20, "eveb_norm": 18},
    "Utilities": {"type": "verdi", "pe_norm": 16, "eveb_norm": 12},
}

def get_fundamental_data(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        
        sector = info.get("sector", "Unknown")
        sp = SECTOR_PROFILES.get(sector, {"type": "verdi", "pe_norm": 15, "eveb_norm": 10})
        
        pe = info.get("trailingPE")
        ev_ebitda = info.get("enterpriseToEbitda")
        roe = info.get("returnOnEquity")
        fcf = info.get("freeCashflow")
        mkt_cap = info.get("marketCap")
        debt_equity = info.get("debtToEquity")
        op_margin = info.get("operatingMargins")
        div_yield = info.get("dividendYield")
        rev_growth = info.get("revenueGrowth")
        current_ratio = info.get("currentRatio")
        earnings_growth = info.get("earningsGrowth")
        
        fcf_yield = (fcf / mkt_cap * 100) if (fcf and mkt_cap) else None
        
        pe_adj = (pe / sp["pe_norm"]) if pe else None
        eveb_adj = (ev_ebitda / sp["eveb_norm"]) if ev_ebitda else None
        
        # Fundamental score
        fund_score = 5.0
        
        if roe:
            r = roe * 100
            if r > 20: fund_score += 1.5
            elif r > 15: fund_score += 1.0
            elif r < 5: fund_score -= 1.0
        
        if fcf_yield:
            if fcf_yield > 8: fund_score += 1.5
            elif fcf_yield > 4: fund_score += 0.5
            elif fcf_yield < 0: fund_score -= 1.5
        
        if pe_adj:
            if pe_adj < 0.8: fund_score += 1.0
            elif pe_adj > 1.5: fund_score -= 1.0
        
        if debt_equity:
            if debt_equity < 50: fund_score += 0.5
            elif debt_equity > 200: fund_score -= 1.0
        
        if op_margin:
            m = op_margin * 100
            if m > 20: fund_score += 0.5
            elif m < 5: fund_score -= 0.5
        
        if rev_growth:
            g = rev_growth * 100
            if g > 20: fund_score += 1.0
            elif g > 10: fund_score += 0.5
            elif g < -5: fund_score -= 1.0
        
        if div_yield:
            if div_yield * 100 > 3: fund_score += 0.5
        
        fund_score = max(1, min(10, fund_score))
        
        if fund_score >= 7: fund_rec = "KJØP"
        elif fund_score <= 4: fund_rec = "SELG"
        else: fund_rec = "HOLD"
        
        # Analyst targets
        target_mean = info.get("targetMeanPrice")
        target_high = info.get("targetHighPrice")
        target_low = info.get("targetLowPrice")
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        
        upside = None
        if target_mean and price and price > 0:
            upside = ((target_mean - price) / price) * 100
        
        analysts = info.get("numberOfAnalystOpinions", 0)
        rec = info.get("recommendationKey", "").upper()
        
        return {
            "sector": sector,
            "sector_type": sp["type"],
            "name": info.get("longName", ticker),
            "pe": round(pe, 1) if pe else None,
            "pe_adj": round(pe_adj, 2) if pe_adj else None,
            "ev_ebitda": round(ev_ebitda, 1) if ev_ebitda else None,
            "eveb_adj": round(eveb_adj, 2) if eveb_adj else None,
            "roe": round(roe * 100, 1) if roe else None,
            "fcf_yield": round(fcf_yield, 1) if fcf_yield else None,
            "debt_equity": round(debt_equity, 0) if debt_equity else None,
            "op_margin": round(op_margin * 100, 1) if op_margin else None,
            "div_yield": round(div_yield * 100, 2) if div_yield else None,
            "rev_growth": round(rev_growth * 100, 1) if rev_growth else None,
            "earnings_growth": round(earnings_growth * 100, 1) if earnings_growth else None,
            "current_ratio": round(current_ratio, 2) if current_ratio else None,
            "fund_score": round(fund_score, 1),
            "fund_recommendation": fund_rec,
            "target_mean": round(target_mean, 2) if target_mean else None,
            "target_high": round(target_high, 2) if target_high else None,
            "target_low": round(target_low, 2) if target_low else None,
            "upside": round(upside, 1) if upside else None,
            "analyst_count": analysts,
            "consensus": rec,
        }
    except Exception as e:
        print(f"  Feil ved fundamental data for {ticker}: {e}")
        return None

# ============================================================
# NYHETER FRA OSLO BØRS
# ============================================================

def get_news(ticker):
    try:
        symbol = ticker.replace(".OL", "")
        stock = yf.Ticker(ticker)
        news = stock.news[:5] if stock.news else []
        result = []
        for n in news:
            content = n.get("content", {})
            result.append({
                "title": content.get("title", n.get("title", "")),
                "url": content.get("canonicalUrl", {}).get("url", "") or n.get("link", ""),
                "date": datetime.datetime.fromtimestamp(
                    content.get("pubDate", n.get("providerPublishTime", 0))
                    if isinstance(content.get("pubDate", 0), (int, float))
                    else time.time()
                ).strftime("%d.%m.%Y") if content.get("pubDate") or n.get("providerPublishTime") else "",
            })
        return result
    except:
        return []

# ============================================================
# MEGLERHUS-DATA (simulert — bytt ut med BørsXtra-integrasjon)
# ============================================================

def get_broker_favorites():
    """
    I produksjon: parse BørsXtra/Xtrainvestor daglig nyhetsbrev (e-post eller API).
    Her returneres realistiske simulerte data som placeholder.
    """
    brokers = {
        "Arctic Securities": {
            "favorites": ["EQNR.OL", "AKERBP.OL", "SUBC.OL", "DNB.OL", "SCATC.OL"],
            "top_pick": "AKERBP.OL",
            "comment": "Fokus på energi og finans for Q2 2025"
        },
        "Fearnley Securities": {
            "favorites": ["FRONTLINE.OL", "MOWI.OL", "SALM.OL", "NHY.OL", "YAR.OL"],
            "top_pick": "FRONTLINE.OL",
            "comment": "Shipping og havbruk favorisert"
        },
        "SpareBank 1 Markets": {
            "favorites": ["DNB.OL", "SRBANK.OL", "ORK.OL", "TEL.OL", "KAHOT.OL"],
            "top_pick": "DNB.OL",
            "comment": "Banker og konsumer i fokus"
        },
        "DNB Markets": {
            "favorites": ["EQNR.OL", "NHY.OL", "MOWI.OL", "AKER.OL", "RECSI.OL"],
            "top_pick": "NHY.OL",
            "comment": "Industri og grønn energi"
        },
        "Carnegie": {
            "favorites": ["SCATC.OL", "KAHOT.OL", "BOUVET.OL", "CRAYON.OL", "ATEA.OL"],
            "top_pick": "SCATC.OL",
            "comment": "Teknologi og fornybar energi"
        },
        "Pareto Securities": {
            "favorites": ["AKERBP.OL", "EQNR.OL", "SDRL.OL", "PGS.OL", "TGS.OL"],
            "top_pick": "AKERBP.OL",
            "comment": "Olje og gass dominerer portefølje"
        },
        "Norne Securities": {
            "favorites": ["LSG.OL", "BAKKA.OL", "GSF.OL", "YAR.OL", "ORK.OL"],
            "top_pick": "LSG.OL",
            "comment": "Sjømat og landbruk"
        },
        "Nordea Markets": {
            "favorites": ["DNB.OL", "TEL.OL", "EQNR.OL", "NHY.OL", "MOWI.OL"],
            "top_pick": "TEL.OL",
            "comment": "Defensive kvalitetsaksjer"
        },
        "Clarksons": {
            "favorites": ["FRONTLINE.OL", "SDRL.OL", "SUBC.OL", "ARCHER.OL", "PARSG.OL"],
            "top_pick": "FRONTLINE.OL",
            "comment": "Shipping og offshore"
        },
    }
    
    # Konsensus: tell opp forekomster
    all_picks = []
    for b in brokers.values():
        all_picks.extend(b["favorites"])
    from collections import Counter
    counts = Counter(all_picks)
    consensus = [{"ticker": t, "count": c, "brokers": c} for t, c in counts.most_common(10)]
    
    # Historikk (simulert 12 mnd)
    today = datetime.date.today()
    history = []
    for i in range(52):
        week_date = (today - datetime.timedelta(weeks=i)).isoformat()
        history.append({
            "date": week_date,
            "top_consensus": random.choice(["EQNR.OL", "DNB.OL", "AKERBP.OL", "MOWI.OL", "NHY.OL"]),
        })
    
    return {"brokers": brokers, "consensus": consensus, "history": history}

# ============================================================
# KOMBINERT SCORE OG PORTEFØLJE-TIPS
# ============================================================

def calculate_combined_score(tech_data, fund_data):
    if not tech_data or not fund_data:
        return 5.0
    tech_raw = tech_data.get("tech_score", 0)
    tech_normalized = min(10, max(1, 5 + tech_raw * 0.8))
    fund = fund_data.get("fund_score", 5)
    combined = (tech_normalized * TECH_WEIGHT) + (fund * FUND_WEIGHT)
    return round(min(10, max(1, combined)), 1)

# ============================================================
# MINERVINI SCREENER FOR OSLO BØRS
# ============================================================

def run_minervini_screener(tickers):
    print("\n🔍 Kjører Minervini-screener...")
    results = []
    for ticker in tickers:
        print(f"  Screener: {ticker}")
        tech = get_technical_indicators(ticker)
        fund = get_fundamental_data(ticker)
        if tech and tech.get("minervini"):
            m = tech["minervini"]
            
            # Fundamentale Minervini-kriterier
            eps_growth = (fund.get("earnings_growth") or 0) if fund else 0
            rev_growth_val = (fund.get("rev_growth") or 0) if fund else 0
            op_margin_val = (fund.get("op_margin") or 0) if fund else 0
            roe_val = (fund.get("roe") or 0) if fund else 0
            
            fund_criteria = {
                "eps_growth_20pct": eps_growth > MIN_EPS_GROWTH,
                "revenue_growth_15pct": rev_growth_val > MIN_REV_GROWTH,
                "positive_margins": op_margin_val > 0,
                "roe_above_17": roe_val > MIN_ROE,
            }
            fund_score_minervini = sum(1 for v in fund_criteria.values() if v)
            
            total_criteria = 8 + 4  # 8 tekniske + 4 fundamentale
            total_passed = m["score"] + fund_score_minervini
            
            results.append({
                "ticker": ticker,
                "name": (fund.get("name", ticker) if fund else ticker),
                "price": tech.get("price"),
                "tech_criteria": m,
                "fund_criteria": fund_criteria,
                "total_passed": total_passed,
                "total_criteria": total_criteria,
                "passes_all_tech": m["passes_all"],
                "passes_all_fund": fund_score_minervini == 4,
                "passes_all": m["passes_all"] and fund_score_minervini == 4,
                "rs_rating": m.get("rs_rating"),
                "ret_12m": tech.get("ret_12m"),
                "fund_data": fund,
                "tech_data": tech,
            })
        time.sleep(API_DELAY)
    
    results.sort(key=lambda x: x["total_passed"], reverse=True)
    passed = sum(1 for r in results if r["passes_all"])
    failed = len(results) - passed
    
    return {"results": results, "passed": passed, "failed": failed, "total": len(results)}

# ============================================================
# HOVED-ANALYSE
# ============================================================

def analyze_portfolio():
    global OSEBX_TICKERS
    print("=" * 60)
    print("📊 Oslo Børs Portfolio Analyzer")
    print(f"📅 {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}")
    print("=" * 60)
    
    # Hent alle Oslo Børs-tickers dynamisk ved oppstart
    if not OSEBX_TICKERS:
        OSEBX_TICKERS = fetch_oslo_bors_tickers(max_tickers=0)
    
    portfolio_data = {}
    
    print("\n📈 Henter porteføljedata...")
    for ticker, shares in MY_PORTFOLIO.items():
        print(f"  Analyserer {ticker}...")
        tech = get_technical_indicators(ticker)
        fund = get_fundamental_data(ticker)
        news = get_news(ticker)
        combined = calculate_combined_score(tech, fund)
        
        portfolio_data[ticker] = {
            "ticker": ticker,
            "shares": shares,
            "technical": tech,
            "fundamental": fund,
            "news": news,
            "combined_score": combined,
        }
        time.sleep(API_DELAY)
    

    print("\n🏦 Henter meglerhus-favoritter...")
    broker_data = get_broker_favorites()
    
    # Finn månedens investering (høyest combined score i porteføljen)
    valid_stocks = [(t, d) for t, d in portfolio_data.items() if d["combined_score"]]
    month_pick = max(valid_stocks, key=lambda x: x[1]["combined_score"]) if valid_stocks else None
    
    # Tips til ny aksje (ikke i portefølje, høyest score blant OSEBX)
    external_candidates = [t for t in OSEBX_TICKERS if t not in MY_PORTFOLIO]
    new_tip = None
    if external_candidates:
        # Enkel heuristikk basert på momentum
        tip_ticker = random.choice(external_candidates[:5])
        tip_tech = get_technical_indicators(tip_ticker)
        tip_fund = get_fundamental_data(tip_ticker)
        tip_score = calculate_combined_score(tip_tech, tip_fund)
        new_tip = {
            "ticker": tip_ticker,
            "technical": tip_tech,
            "fundamental": tip_fund,
            "combined_score": tip_score,
        }
    
    print("\n🔬 Kjører Minervini-screener for hele Oslo Børs...")
    all_screen_tickers = list({*OSEBX_TICKERS, *MY_PORTFOLIO.keys()})
    minervini_results = run_minervini_screener(all_screen_tickers)
    
    return {
        "portfolio": portfolio_data,
        "broker_data": broker_data,
        "month_pick": month_pick,
        "new_tip": new_tip,
        "minervini": minervini_results,
        "generated_at": datetime.datetime.now().strftime("%d.%m.%Y %H:%M"),
    }

# ============================================================
# HTML GENERATOR
# ============================================================

def score_color(score):
    if score >= SCORE_POSITIVE: return "#00d4aa"
    elif score >= SCORE_NEUTRAL: return "#f59e0b"
    else: return "#ef4444"

def rec_badge(rec):
    colors = {"KJØP": "#00d4aa", "HOLD": "#f59e0b", "SELG": "#ef4444"}
    c = colors.get(rec, "#94a3b8")
    return f'<span class="badge" style="background:{c}20;color:{c};border:1px solid {c}40">{rec}</span>'

def na(val, suffix="", prefix=""):
    if val is None: return '<span class="na">N/A</span>'
    return f"{prefix}{val}{suffix}"

def generate_html(data):
    p = data["portfolio"]
    bd = data["broker_data"]
    mp = data["month_pick"]
    nt = data["new_tip"]
    mn = data["minervini"]
    gen = data["generated_at"]
    
    # Sektor-fordeling
    sector_map = {}
    for ticker, d in p.items():
        f = d.get("fundamental")
        sec = (f.get("sector") if f else None) or "Ukjent"
        if sec not in sector_map:
            sector_map[sec] = []
        sector_map[sec].append(ticker)
    
    sector_colors = {
        "Energy": "#f97316", "Financial Services": "#3b82f6", "Consumer Defensive": "#10b981",
        "Technology": "#8b5cf6", "Healthcare": "#ec4899", "Industrials": "#6366f1",
        "Basic Materials": "#84cc16", "Communication Services": "#06b6d4",
        "Consumer Cyclical": "#f59e0b", "Real Estate": "#a78bfa", "Utilities": "#94a3b8",
        "Ukjent": "#475569",
    }
    
    # Portfolio rows
    port_rows = ""
    for ticker, d in p.items():
        tech = d.get("technical") or {}
        fund = d.get("fundamental") or {}
        cs = d.get("combined_score", 5)
        price = tech.get("price", 0)
        value = price * d["shares"]
        
        sec = fund.get("sector", "Ukjent")
        sec_color = sector_colors.get(sec, "#475569")
        
        port_rows += f"""
        <tr class="stock-row" onclick="openStockModal('{ticker}')" style="cursor:pointer">
            <td><strong style="color:#e2e8f0">{ticker.replace('.OL','')}</strong><br>
                <small style="color:#64748b">{fund.get('name','')[:22] if fund else ''}</small></td>
            <td style="color:#e2e8f0">{na(price, ' kr')}</td>
            <td>{d['shares']}</td>
            <td style="color:#94a3b8">{value:,.0f} kr</td>
            <td><span style="color:{sec_color};font-size:0.8em">●</span> {sec}</td>
            <td>{rec_badge(tech.get('tech_recommendation',''))}</td>
            <td>{rec_badge(fund.get('fund_recommendation',''))}</td>
            <td><span class="score-pill" style="background:{score_color(cs)}20;color:{score_color(cs)};border:1px solid {score_color(cs)}40">{cs}/10</span></td>
        </tr>"""
    
    # Technical tab rows
    tech_rows = ""
    for ticker, d in p.items():
        tech = d.get("technical") or {}
        rsi_color = "#ef4444" if (tech.get("rsi",50) or 50) > 70 else "#00d4aa" if (tech.get("rsi",50) or 50) < 30 else "#94a3b8"
        macd_color = "#00d4aa" if (tech.get("macd_hist",0) or 0) > 0 else "#ef4444"
        gc_color = "#00d4aa" if tech.get("golden_cross") else "#ef4444"
        
        tech_rows += f"""
        <tr>
            <td><strong style="color:#e2e8f0">{ticker.replace('.OL','')}</strong></td>
            <td style="color:{rsi_color}">{na(tech.get('rsi'))}</td>
            <td>{na(tech.get('ma50'), ' kr')}<br><small style="color:#64748b">MA200: {na(tech.get('ma200'), ' kr')}</small></td>
            <td style="color:{gc_color}">{'✓ Ja' if tech.get('golden_cross') else '✗ Nei'}</td>
            <td style="color:{macd_color}">{na(tech.get('macd'))}<br><small>Hist: {na(tech.get('macd_hist'))}</small></td>
            <td>{na(tech.get('bb_pct_b'))}</td>
            <td>{na(tech.get('atr_pct'), '%')}</td>
            <td>{na(tech.get('ret_3m'), '%')} / {na(tech.get('ret_12m'), '%')}</td>
            <td>{na(tech.get('pos_52w'), '%')}</td>
            <td>{rec_badge(tech.get('tech_recommendation',''))}</td>
        </tr>"""
    
    # Fundamental tab rows
    fund_rows = ""
    for ticker, d in p.items():
        fund = d.get("fundamental") or {}
        f_score = fund.get("fund_score", 5)
        
        fund_rows += f"""
        <tr>
            <td><strong style="color:#e2e8f0">{ticker.replace('.OL','')}</strong><br>
                <small style="color:#64748b">{fund.get('sector_type','').upper()}</small></td>
            <td>{na(fund.get('roe'), '%')}</td>
            <td>{na(fund.get('fcf_yield'), '%')}</td>
            <td>{na(fund.get('pe'))} <small style="color:#64748b">({na(fund.get('pe_adj'))}x)</small></td>
            <td>{na(fund.get('ev_ebitda'))} <small style="color:#64748b">({na(fund.get('eveb_adj'))}x)</small></td>
            <td>{na(fund.get('debt_equity'))}</td>
            <td>{na(fund.get('op_margin'), '%')}</td>
            <td>{na(fund.get('div_yield'), '%')}</td>
            <td>{na(fund.get('rev_growth'), '%')}</td>
            <td>{na(fund.get('current_ratio'))}</td>
            <td><span class="score-pill" style="background:{score_color(f_score)}20;color:{score_color(f_score)};border:1px solid {score_color(f_score)}40">{f_score}</span></td>
        </tr>"""
    
    # Price target rows
    target_rows = ""
    for ticker, d in p.items():
        fund = d.get("fundamental") or {}
        tech = d.get("technical") or {}
        upside = fund.get("upside")
        upside_color = "#00d4aa" if (upside or 0) > 10 else "#ef4444" if (upside or 0) < -10 else "#f59e0b"
        
        target_rows += f"""
        <tr>
            <td><strong style="color:#e2e8f0">{ticker.replace('.OL','')}</strong></td>
            <td>{na(tech.get('price'), ' kr')}</td>
            <td style="color:{upside_color};font-weight:600">{na(upside, '%', '+' if (upside or 0) > 0 else '')}</td>
            <td>{na(fund.get('target_mean'), ' kr')}</td>
            <td>{na(fund.get('target_low'), ' kr')} – {na(fund.get('target_high'), ' kr')}</td>
            <td>{na(fund.get('analyst_count'))} analytikere</td>
            <td>{rec_badge(fund.get('consensus',''))}</td>
        </tr>"""
    
    # Broker favorites
    broker_html = ""
    for broker_name, bdata in bd["brokers"].items():
        favs = " ".join([f'<span class="broker-tag">{t.replace(".OL","")}</span>' for t in bdata["favorites"]])
        top = bdata["top_pick"].replace(".OL","")
        broker_html += f"""
        <div class="broker-card">
            <div class="broker-header">
                <strong>{broker_name}</strong>
                <span class="top-pick-badge">Top pick: {top}</span>
            </div>
            <div class="broker-favs">{favs}</div>
            <p class="broker-comment">{bdata['comment']}</p>
        </div>"""
    
    # Consensus table
    consensus_rows = ""
    for i, c in enumerate(bd["consensus"][:10], 1):
        bar_width = int(c["count"] / 9 * 100)
        consensus_rows += f"""
        <tr>
            <td style="color:#94a3b8">{i}</td>
            <td><strong style="color:#e2e8f0">{c['ticker'].replace('.OL','')}</strong></td>
            <td>
                <div style="display:flex;align-items:center;gap:8px">
                    <div style="background:#1e293b;border-radius:4px;width:100px;height:6px">
                        <div style="background:#00d4aa;border-radius:4px;width:{bar_width}%;height:100%"></div>
                    </div>
                    <span style="color:#00d4aa">{c['count']} hus</span>
                </div>
            </td>
        </tr>"""
    
    # Minervini screener rows
    min_rows = ""
    for r in mn["results"]:
        passed = r["total_passed"]
        total = r["total_criteria"]
        pct = int(passed / total * 100)
        
        if r["passes_all"]:
            row_class = 'class="minervini-perfect"'
            star = '⭐ '
        elif passed >= 10:
            row_class = 'class="minervini-strong"'
            star = ''
        else:
            row_class = ''
            star = ''
        
        # Criteria badges
        tech_c = r["tech_criteria"]
        crit_badges = ""
        criteria_map = [
            ("above_ma50", "P>MA50"),
            ("above_ma150", "P>MA150"),
            ("above_ma200", "P>MA200"),
            ("ma50_above_ma150", "MA50>MA150"),
            ("ma150_above_ma200", "MA150>MA200"),
            ("ma200_trending_up", "MA200↑"),
            ("within_25_of_high", "<25% fra topp"),
            ("rs_above_70", f"RS>{tech_c.get('rs_rating','?')}"),
        ]
        for key, label in criteria_map:
            ok = tech_c.get(key, False)
            crit_badges += f'<span class="crit-badge {"pass" if ok else "fail"}">{label}</span>'
        
        fund_c = r.get("fund_criteria", {})
        fund_map = [
            ("eps_growth_20pct", "EPS>20%"),
            ("revenue_growth_15pct", "Rev>15%"),
            ("positive_margins", "Margin+"),
            ("roe_above_17", "ROE>17%"),
        ]
        for key, label in fund_map:
            ok = fund_c.get(key, False)
            crit_badges += f'<span class="crit-badge {"pass" if ok else "fail"}">{label}</span>'
        
        ticker_display = r["ticker"].replace(".OL","")
        
        min_rows += f"""
        <tr {row_class}>
            <td>
                <strong style="color:#e2e8f0">{star}{ticker_display}</strong>
                {'<span style="color:#ffd700;font-size:0.75em;margin-left:4px">ALLE KRITERIER</span>' if r['passes_all'] else ''}
                <br><small style="color:#64748b">{r['name'][:28]}</small>
            </td>
            <td>{na(r.get('price'), ' kr')}</td>
            <td>
                <div class="score-bar-wrap">
                    <div class="score-bar" style="width:{pct}%;background:{'#ffd700' if r['passes_all'] else '#00d4aa' if pct>=70 else '#f59e0b' if pct>=50 else '#ef4444'}"></div>
                </div>
                <span style="color:#94a3b8;font-size:0.8em">{passed}/{total}</span>
            </td>
            <td>{na(r.get('rs_rating'))}</td>
            <td>{na(r.get('ret_12m'), '%')}</td>
            <td><div class="criteria-wrap">{crit_badges}</div></td>
        </tr>"""
    
    # Stock modals data
    modals_js_data = {}
    for ticker, d in p.items():
        tech = d.get("technical") or {}
        fund = d.get("fundamental") or {}
        news = d.get("news") or []
        cs = d.get("combined_score", 5)
        
        news_html = "".join([
            f'<div class="news-item"><a href="{n["url"]}" target="_blank" style="color:#38bdf8;text-decoration:none">{n["title"]}</a><small style="color:#64748b;display:block">{n["date"]}</small></div>'
            for n in news
        ]) or "<p style='color:#64748b'>Ingen nyheter tilgjengelig</p>"
        
        modals_js_data[ticker] = {
            "name": fund.get("name", ticker) if fund else ticker,
            "price": tech.get("price"),
            "tech_rec": tech.get("tech_recommendation", "HOLD"),
            "fund_rec": fund.get("fund_recommendation", "HOLD"),
            "combined": cs,
            "rsi": tech.get("rsi"),
            "ma50": tech.get("ma50"),
            "ma200": tech.get("ma200"),
            "golden_cross": tech.get("golden_cross"),
            "pe": fund.get("pe") if fund else None,
            "roe": fund.get("roe") if fund else None,
            "div_yield": fund.get("div_yield") if fund else None,
            "upside": fund.get("upside") if fund else None,
            "news_html": news_html,
            "sector": fund.get("sector", "Ukjent") if fund else "Ukjent",
        }
    
    modals_json = json.dumps(modals_js_data, ensure_ascii=False, default=str)
    
    # Sektor-diagram data
    sector_chart_data = json.dumps([
        {"sector": sec, "count": len(tickers), "tickers": tickers, "color": sector_colors.get(sec, "#475569")}
        for sec, tickers in sector_map.items()
    ], ensure_ascii=False)
    
    # Month pick og new tip
    mp_html = ""
    if mp:
        mt, md = mp
        mf = md.get("fundamental") or {}
        mtech = md.get("technical") or {}
        mcs = md.get("combined_score", 5)
        mp_html = f"""
        <div class="tip-content">
            <div class="tip-ticker">{mt.replace('.OL','')}</div>
            <div class="tip-name">{mf.get('name', mt)[:30] if mf else mt}</div>
            <div class="tip-score" style="color:{score_color(mcs)}">{mcs}/10</div>
            <div style="color:#94a3b8;font-size:0.85em;margin-top:8px">
                {rec_badge(mtech.get('tech_recommendation',''))} {rec_badge(mf.get('fund_recommendation','') if mf else '')}
            </div>
            <p style="color:#64748b;font-size:0.8em;margin-top:8px">
                RSI: {mtech.get('rsi','N/A')} | ROE: {mf.get('roe','N/A') if mf else 'N/A'}%
            </p>
        </div>"""
    
    nt_html = ""
    if nt:
        ntf = nt.get("fundamental") or {}
        nttech = nt.get("technical") or {}
        ntcs = nt.get("combined_score", 5)
        nt_html = f"""
        <div class="tip-content">
            <div class="tip-ticker">{nt['ticker'].replace('.OL','')}</div>
            <div class="tip-name">{ntf.get('name', nt['ticker'])[:30] if ntf else nt['ticker']}</div>
            <div class="tip-score" style="color:{score_color(ntcs)}">{ntcs}/10</div>
            <div style="color:#94a3b8;font-size:0.85em;margin-top:8px">
                {rec_badge(nttech.get('tech_recommendation',''))} {rec_badge(ntf.get('fund_recommendation','') if ntf else '')}
            </div>
            <p style="color:#64748b;font-size:0.8em;margin-top:8px">
                {ntf.get('sector','') if ntf else ''} | Upside: {na(ntf.get('upside') if ntf else None, '%')}
            </p>
        </div>"""
    
    # Total portfolio value
    total_value = sum(
        (d.get("technical") or {}).get("price", 0) * d["shares"]
        for d in p.values()
    )
    
    html = f"""<!DOCTYPE html>
<html lang="no">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Oslo Børs Portfolio Analyzer</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Syne:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
:root {{
    --bg: #070d1a;
    --surface: #0d1829;
    --surface2: #111e33;
    --border: #1e2d47;
    --accent: #00d4aa;
    --accent2: #3b82f6;
    --text: #e2e8f0;
    --muted: #64748b;
    --danger: #ef4444;
    --warning: #f59e0b;
    --gold: #ffd700;
}}
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
    font-family: 'Syne', sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    background-image:
        radial-gradient(ellipse 80% 50% at 50% -20%, rgba(0,212,170,0.05) 0%, transparent 70%),
        radial-gradient(ellipse 40% 30% at 80% 80%, rgba(59,130,246,0.04) 0%, transparent 60%);
}}

/* HEADER */
.header {{
    border-bottom: 1px solid var(--border);
    padding: 20px 32px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: rgba(13,24,41,0.95);
    position: sticky;
    top: 0;
    z-index: 100;
    backdrop-filter: blur(10px);
}}
.header-logo {{
    font-family: 'Space Mono', monospace;
    font-size: 1.1rem;
    font-weight: 700;
    color: var(--accent);
    letter-spacing: -0.5px;
}}
.header-logo span {{ color: var(--text); }}
.header-meta {{
    font-size: 0.78rem;
    color: var(--muted);
    font-family: 'Space Mono', monospace;
}}
.header-value {{
    font-size: 0.9rem;
    color: var(--accent);
    font-family: 'Space Mono', monospace;
    font-weight: 700;
}}

/* TABS */
.tab-bar {{
    display: flex;
    gap: 0;
    border-bottom: 1px solid var(--border);
    padding: 0 32px;
    overflow-x: auto;
    background: var(--surface);
}}
.tab-btn {{
    padding: 14px 20px;
    border: none;
    background: none;
    color: var(--muted);
    font-family: 'Syne', sans-serif;
    font-size: 0.85rem;
    font-weight: 600;
    cursor: pointer;
    white-space: nowrap;
    border-bottom: 2px solid transparent;
    transition: all 0.2s;
    letter-spacing: 0.3px;
}}
.tab-btn:hover {{ color: var(--text); }}
.tab-btn.active {{
    color: var(--accent);
    border-bottom-color: var(--accent);
}}

/* CONTENT */
.tab-content {{ display: none; padding: 24px 32px; }}
.tab-content.active {{ display: block; }}

/* GRID */
.grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
.grid-3 {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }}
@media (max-width: 900px) {{ .grid-2, .grid-3 {{ grid-template-columns: 1fr; }} }}

/* CARDS */
.card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
}}
.card-title {{
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 16px;
}}

/* TABLES */
.table-wrap {{ overflow-x: auto; }}
table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.875rem;
}}
th {{
    text-align: left;
    padding: 10px 12px;
    color: var(--muted);
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 1px;
    text-transform: uppercase;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
    background: var(--surface);
    position: sticky;
    top: 0;
}}
td {{
    padding: 12px 12px;
    border-bottom: 1px solid rgba(30,45,71,0.5);
    color: var(--muted);
    vertical-align: middle;
}}
tr:hover td {{ background: rgba(255,255,255,0.02); }}
.stock-row:hover {{ background: rgba(0,212,170,0.03) !important; }}

/* BADGES */
.badge {{
    display: inline-block;
    padding: 3px 10px;
    border-radius: 20px;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.5px;
}}
.score-pill {{
    display: inline-block;
    padding: 3px 10px;
    border-radius: 20px;
    font-size: 0.8rem;
    font-weight: 700;
    font-family: 'Space Mono', monospace;
}}
.na {{ color: var(--muted); font-style: italic; }}

/* SECTOR CHART */
#sectorCanvas {{ width: 100%; height: 300px; }}

/* TIP BOXES */
.tip-box {{
    background: linear-gradient(135deg, var(--surface) 0%, rgba(0,212,170,0.04) 100%);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
}}
.tip-ticker {{
    font-family: 'Space Mono', monospace;
    font-size: 2rem;
    font-weight: 700;
    color: var(--accent);
}}
.tip-name {{ color: var(--muted); font-size: 0.85rem; margin-top: 4px; }}
.tip-score {{
    font-family: 'Space Mono', monospace;
    font-size: 2.5rem;
    font-weight: 700;
    margin-top: 12px;
}}

/* BROKER CARDS */
.broker-card {{
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px;
    margin-bottom: 12px;
}}
.broker-header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 10px;
}}
.top-pick-badge {{
    background: rgba(0,212,170,0.1);
    color: var(--accent);
    border: 1px solid rgba(0,212,170,0.2);
    padding: 2px 10px;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 700;
}}
.broker-favs {{ display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }}
.broker-tag {{
    background: rgba(59,130,246,0.1);
    color: #93c5fd;
    border: 1px solid rgba(59,130,246,0.2);
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.78rem;
    font-family: 'Space Mono', monospace;
}}
.broker-comment {{ color: var(--muted); font-size: 0.8rem; }}

/* MINERVINI */
.minervini-perfect td {{ background: rgba(255,215,0,0.04) !important; }}
.minervini-perfect:hover td {{ background: rgba(255,215,0,0.07) !important; }}
.minervini-strong td {{ background: rgba(0,212,170,0.03) !important; }}
.score-bar-wrap {{
    background: var(--surface2);
    border-radius: 4px;
    height: 6px;
    width: 100px;
    margin-bottom: 4px;
}}
.score-bar {{ height: 100%; border-radius: 4px; transition: width 0.3s; }}
.criteria-wrap {{ display: flex; flex-wrap: wrap; gap: 4px; }}
.crit-badge {{
    display: inline-block;
    padding: 2px 7px;
    border-radius: 4px;
    font-size: 0.68rem;
    font-weight: 600;
    font-family: 'Space Mono', monospace;
    white-space: nowrap;
}}
.crit-badge.pass {{ background: rgba(0,212,170,0.15); color: var(--accent); }}
.crit-badge.fail {{ background: rgba(239,68,68,0.1); color: #f87171; text-decoration: line-through; }}

/* SCREENER STATS */
.screener-stats {{
    display: flex;
    gap: 16px;
    margin-bottom: 24px;
}}
.stat-box {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px 24px;
    text-align: center;
}}
.stat-num {{
    font-family: 'Space Mono', monospace;
    font-size: 2rem;
    font-weight: 700;
}}
.stat-label {{ font-size: 0.75rem; color: var(--muted); margin-top: 4px; text-transform: uppercase; letter-spacing: 1px; }}

/* MODAL */
.modal-overlay {{
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(7,13,26,0.9);
    backdrop-filter: blur(8px);
    z-index: 1000;
    align-items: center;
    justify-content: center;
}}
.modal-overlay.open {{ display: flex; }}
.modal {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 32px;
    max-width: 600px;
    width: 90%;
    max-height: 80vh;
    overflow-y: auto;
}}
.modal-header {{ display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 24px; }}
.modal-ticker {{
    font-family: 'Space Mono', monospace;
    font-size: 1.8rem;
    font-weight: 700;
    color: var(--accent);
}}
.modal-close {{ background: none; border: none; color: var(--muted); cursor: pointer; font-size: 1.5rem; }}
.modal-grid {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; margin-bottom: 20px; }}
.modal-stat {{
    background: var(--surface2);
    border-radius: 8px;
    padding: 12px;
    text-align: center;
}}
.modal-stat-val {{ font-size: 1.2rem; font-weight: 700; font-family: 'Space Mono', monospace; }}
.modal-stat-label {{ font-size: 0.72rem; color: var(--muted); margin-top: 4px; text-transform: uppercase; letter-spacing: 1px; }}
.news-item {{ padding: 10px 0; border-bottom: 1px solid var(--border); }}
.news-item:last-child {{ border-bottom: none; }}

/* HISTORY */
.history-list {{ max-height: 300px; overflow-y: auto; }}
.history-item {{
    display: flex;
    justify-content: space-between;
    padding: 8px 12px;
    border-bottom: 1px solid rgba(30,45,71,0.5);
    font-size: 0.82rem;
}}
.history-item:hover {{ background: rgba(255,255,255,0.02); }}

/* SCROLLBAR */
::-webkit-scrollbar {{ width: 6px; height: 6px; }}
::-webkit-scrollbar-track {{ background: var(--bg); }}
::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 3px; }}
::-webkit-scrollbar-thumb:hover {{ background: var(--muted); }}

/* PULSE ANIMATION */
@keyframes pulse-glow {{
    0%, 100% {{ box-shadow: 0 0 0 0 rgba(0,212,170,0); }}
    50% {{ box-shadow: 0 0 20px 4px rgba(0,212,170,0.15); }}
}}
.pulse {{ animation: pulse-glow 3s infinite; }}

/* SECTION TITLE */
.section-title {{
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 20px;
    padding-bottom: 10px;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    gap: 8px;
}}
.section-title::before {{
    content: '';
    display: inline-block;
    width: 3px;
    height: 14px;
    background: var(--accent);
    border-radius: 2px;
}}
</style>
</head>
<body>

<div class="header">
    <div class="header-logo">OSLO<span>BØR</span>S<span style="color:var(--accent)">.</span>AI</div>
    <div class="header-meta">Oppdatert: {gen} · {len(p)} aksjer i portefølje</div>
    <div class="header-value">Portefølje: {total_value:,.0f} kr</div>
</div>

<div class="tab-bar">
    <button class="tab-btn active" onclick="showTab('oversikt')">📊 Oversikt</button>
    <button class="tab-btn" onclick="showTab('teknisk')">📈 Teknisk</button>
    <button class="tab-btn" onclick="showTab('fundamental')">🏦 Fundamental</button>
    <button class="tab-btn" onclick="showTab('kursmaal')">🎯 Kursmål</button>
    <button class="tab-btn" onclick="showTab('meglerhus')">🏢 Meglerhus</button>
    <button class="tab-btn" onclick="showTab('minervini')">🔬 Minervini</button>
</div>

<!-- OVERSIKT -->
<div class="tab-content active" id="tab-oversikt">
    <div style="display:grid;grid-template-columns:1fr 380px;gap:24px;margin-bottom:24px">
        
        <!-- Portefølje-tabell -->
        <div class="card">
            <div class="section-title">Mine aksjer</div>
            <div class="table-wrap">
                <table>
                    <thead><tr>
                        <th>Aksje</th><th>Kurs</th><th>Antall</th><th>Verdi</th>
                        <th>Sektor</th><th>Teknisk</th><th>Fundamental</th><th>Score</th>
                    </tr></thead>
                    <tbody>{port_rows}</tbody>
                </table>
            </div>
        </div>
        
        <!-- Høyre kolonne -->
        <div style="display:flex;flex-direction:column;gap:16px">
            
            <!-- Sektor-diagram -->
            <div class="card">
                <div class="section-title">Sektorfordeling</div>
                <canvas id="sectorCanvas"></canvas>
            </div>
            
            <!-- Månedens investering -->
            <div class="tip-box pulse">
                <div class="card-title">⭐ Månedens investering</div>
                {mp_html if mp_html else '<p style="color:var(--muted)">Ingen data</p>'}
            </div>
            
            <!-- Ny aksje-tips -->
            <div class="tip-box" style="border-color:rgba(59,130,246,0.3)">
                <div class="card-title">💡 Ny aksje-tips (ikke i portefølje)</div>
                {nt_html if nt_html else '<p style="color:var(--muted)">Ingen data</p>'}
            </div>
        </div>
    </div>
</div>

<!-- TEKNISK -->
<div class="tab-content" id="tab-teknisk">
    <div class="section-title">Tekniske indikatorer</div>
    <div class="table-wrap">
        <table>
            <thead><tr>
                <th>Aksje</th><th>RSI(14)</th><th>MA50/200</th><th>Gyllent kryss</th>
                <th>MACD</th><th>BB %B</th><th>ATR%</th><th>3M/12M Avk.</th>
                <th>52-ukers pos.</th><th>Anbefaling</th>
            </tr></thead>
            <tbody>{tech_rows}</tbody>
        </table>
    </div>
</div>

<!-- FUNDAMENTAL -->
<div class="tab-content" id="tab-fundamental">
    <div class="section-title">Fundamentale indikatorer (sektorjustert)</div>
    <div class="table-wrap">
        <table>
            <thead><tr>
                <th>Aksje</th><th>ROE</th><th>FCF Yield</th>
                <th>P/E (adj.)</th><th>EV/EBITDA (adj.)</th><th>Gjeldsgrad</th>
                <th>Driftsmargin</th><th>Utbytte</th><th>Vekst</th><th>Likviditet</th>
                <th>Score</th>
            </tr></thead>
            <tbody>{fund_rows}</tbody>
        </table>
    </div>
</div>

<!-- KURSMÅL -->
<div class="tab-content" id="tab-kursmaal">
    <div class="section-title">Analytikere og kursmål</div>
    <div class="table-wrap">
        <table>
            <thead><tr>
                <th>Aksje</th><th>Kurs nå</th><th>Upside</th>
                <th>Snitt kursmål</th><th>Range (lav–høy)</th>
                <th>Analytikere</th><th>Konsensus</th>
            </tr></thead>
            <tbody>{target_rows}</tbody>
        </table>
    </div>
</div>

<!-- MEGLERHUS -->
<div class="tab-content" id="tab-meglerhus">
    <div class="grid-2">
        <div>
            <div class="section-title">Favorittporteføljer per meglerhus</div>
            {broker_html}
        </div>
        <div>
            <div class="section-title">Konsensus — flest meglerhus</div>
            <div class="card" style="margin-bottom:20px">
                <table>
                    <thead><tr><th>#</th><th>Aksje</th><th>Støtte</th></tr></thead>
                    <tbody>{consensus_rows}</tbody>
                </table>
            </div>
            
            <div class="section-title">Historikk — siste 12 måneder</div>
            <div class="card">
                <div class="history-list">
                    {"".join([f'<div class="history-item"><span style="color:var(--muted);font-family:Space Mono,monospace;font-size:0.75em">{h["date"]}</span><span style="color:var(--accent);font-family:Space Mono,monospace">{h["top_consensus"].replace(".OL","")}</span></div>' for h in bd["history"]])}
                </div>
                <p style="color:var(--muted);font-size:0.75rem;margin-top:10px;padding-top:10px;border-top:1px solid var(--border)">
                    * Data fra BørsXtra/Xtrainvestor daglig nyhetsbrev. Koble til e-post-parser for live data.
                </p>
            </div>
        </div>
    </div>
</div>

<!-- MINERVINI SCREENER -->
<div class="tab-content" id="tab-minervini">
    <div class="screener-stats">
        <div class="stat-box">
            <div class="stat-num" style="color:var(--text)">{mn['total']}</div>
            <div class="stat-label">Totalt screenet</div>
        </div>
        <div class="stat-box">
            <div class="stat-num" style="color:var(--accent)">{mn['passed']}</div>
            <div class="stat-label">Alle kriterier ✓</div>
        </div>
        <div class="stat-box">
            <div class="stat-num" style="color:var(--danger)">{mn['failed']}</div>
            <div class="stat-label">Feilet minst ett</div>
        </div>
        <div class="stat-box">
            <div class="stat-num" style="color:var(--warning)">{round(mn['passed']/mn['total']*100) if mn['total'] else 0}%</div>
            <div class="stat-label">Passrate</div>
        </div>
    </div>
    
    <div class="section-title">Minervini Trend Template + Fundamental Screen — Oslo Børs</div>
    <p style="color:var(--muted);font-size:0.82rem;margin-bottom:16px">
        8 tekniske + 4 fundamentale kriterier. ⭐ = alle 12 kriterier bestått. Sortert etter score.
    </p>
    <div class="table-wrap">
        <table>
            <thead><tr>
                <th>Aksje</th><th>Kurs</th><th>Score</th>
                <th>RS Rating</th><th>12M avk.</th><th>Kriterier</th>
            </tr></thead>
            <tbody>{min_rows}</tbody>
        </table>
    </div>
</div>

<!-- MODAL -->
<div class="modal-overlay" id="stockModal" onclick="closeModal(event)">
    <div class="modal" id="modalContent">
        <div class="modal-header">
            <div>
                <div class="modal-ticker" id="modalTicker">—</div>
                <div style="color:var(--muted);font-size:0.85rem;margin-top:4px" id="modalName">—</div>
            </div>
            <button class="modal-close" onclick="closeModalBtn()">✕</button>
        </div>
        <div class="modal-grid" id="modalGrid"></div>
        <div style="margin-bottom:16px" id="modalRecs"></div>
        <div class="card-title">Siste nyheter</div>
        <div id="modalNews"></div>
    </div>
</div>

<script>
const PORTFOLIO_DATA = {modals_json};
const SECTOR_DATA = {sector_chart_data};

function showTab(id) {{
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.getElementById('tab-' + id).classList.add('active');
    event.target.classList.add('active');
    if (id === 'oversikt') drawSectorChart();
}}

function openStockModal(ticker) {{
    const d = PORTFOLIO_DATA[ticker];
    if (!d) return;
    
    document.getElementById('modalTicker').textContent = ticker.replace('.OL','');
    document.getElementById('modalName').textContent = d.name + ' · ' + d.sector;
    
    const scoreColor = d.combined >= 7 ? '#00d4aa' : d.combined >= 5 ? '#f59e0b' : '#ef4444';
    
    document.getElementById('modalGrid').innerHTML = `
        <div class="modal-stat">
            <div class="modal-stat-val" style="color:#e2e8f0">kr ${{d.price ?? 'N/A'}}</div>
            <div class="modal-stat-label">Kurs</div>
        </div>
        <div class="modal-stat">
            <div class="modal-stat-val" style="color:${{scoreColor}}">${{d.combined}}/10</div>
            <div class="modal-stat-label">Score</div>
        </div>
        <div class="modal-stat">
            <div class="modal-stat-val" style="color:#94a3b8">${{d.rsi ?? 'N/A'}}</div>
            <div class="modal-stat-label">RSI</div>
        </div>
        <div class="modal-stat">
            <div class="modal-stat-val" style="color:#94a3b8">${{d.pe ?? 'N/A'}}</div>
            <div class="modal-stat-label">P/E</div>
        </div>
        <div class="modal-stat">
            <div class="modal-stat-val" style="color:#94a3b8">${{d.roe ?? 'N/A'}}%</div>
            <div class="modal-stat-label">ROE</div>
        </div>
        <div class="modal-stat">
            <div class="modal-stat-val" style="color:${{(d.upside ?? 0) > 0 ? '#00d4aa' : '#ef4444'}}">${{d.upside != null ? (d.upside > 0 ? '+' : '') + d.upside + '%' : 'N/A'}}</div>
            <div class="modal-stat-label">Upside</div>
        </div>`;
    
    const recColor = r => r === 'KJØP' ? '#00d4aa' : r === 'SELG' ? '#ef4444' : '#f59e0b';
    document.getElementById('modalRecs').innerHTML = `
        <div style="display:flex;gap:12px;flex-wrap:wrap">
            <div style="flex:1;background:rgba(0,0,0,0.3);border-radius:8px;padding:12px;text-align:center;border:1px solid rgba(255,255,255,0.05)">
                <div style="font-size:0.7rem;color:#64748b;margin-bottom:6px;letter-spacing:1px">TEKNISK</div>
                <div style="font-size:1.1rem;font-weight:700;color:${{recColor(d.tech_rec)}}">${{d.tech_rec}}</div>
            </div>
            <div style="flex:1;background:rgba(0,0,0,0.3);border-radius:8px;padding:12px;text-align:center;border:1px solid rgba(255,255,255,0.05)">
                <div style="font-size:0.7rem;color:#64748b;margin-bottom:6px;letter-spacing:1px">FUNDAMENTAL</div>
                <div style="font-size:1.1rem;font-weight:700;color:${{recColor(d.fund_rec)}}">${{d.fund_rec}}</div>
            </div>
            <div style="flex:1;background:rgba(0,0,0,0.3);border-radius:8px;padding:12px;text-align:center;border:1px solid rgba(255,255,255,0.05)">
                <div style="font-size:0.7rem;color:#64748b;margin-bottom:6px;letter-spacing:1px">MA</div>
                <div style="font-size:0.9rem;color:#94a3b8">50: ${{d.ma50 ?? 'N/A'}}<br>200: ${{d.ma200 ?? 'N/A'}}</div>
            </div>
        </div>`;
    
    document.getElementById('modalNews').innerHTML = d.news_html;
    document.getElementById('stockModal').classList.add('open');
}}

function closeModal(e) {{
    if (e.target.id === 'stockModal') closeModalBtn();
}}
function closeModalBtn() {{
    document.getElementById('stockModal').classList.remove('open');
}}

// Sektor-diagram (Canvas doughnut)
function drawSectorChart() {{
    const canvas = document.getElementById('sectorCanvas');
    if (!canvas || !canvas.getContext) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.width = canvas.offsetWidth;
    const h = canvas.height = 300;
    ctx.clearRect(0, 0, w, h);
    
    const total = SECTOR_DATA.reduce((a, s) => a + s.count, 0);
    if (total === 0) return;
    
    const cx = w * 0.38, cy = h / 2, r = Math.min(cx, cy) - 20;
    let startAngle = -Math.PI / 2;
    
    SECTOR_DATA.forEach(s => {{
        const slice = (s.count / total) * Math.PI * 2;
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.arc(cx, cy, r, startAngle, startAngle + slice);
        ctx.closePath();
        ctx.fillStyle = s.color;
        ctx.fill();
        ctx.strokeStyle = '#070d1a';
        ctx.lineWidth = 2;
        ctx.stroke();
        startAngle += slice;
    }});
    
    // Donut hole
    ctx.beginPath();
    ctx.arc(cx, cy, r * 0.58, 0, Math.PI * 2);
    ctx.fillStyle = '#0d1829';
    ctx.fill();
    
    // Legend
    const lx = cx + r + 20, ly = 30;
    ctx.font = '600 11px Syne, sans-serif';
    SECTOR_DATA.forEach((s, i) => {{
        const y = ly + i * 22;
        ctx.fillStyle = s.color;
        ctx.beginPath();
        ctx.roundRect(lx, y - 7, 10, 10, 3);
        ctx.fill();
        ctx.fillStyle = '#94a3b8';
        ctx.fillText(s.sector.substring(0, 22), lx + 14, y + 2);
        ctx.fillStyle = '#e2e8f0';
        ctx.fillText(s.tickers.map(t => t.replace('.OL','')).join(', ').substring(0, 14), lx + 14, y + 14);
    }});
}}

// Initial render
window.addEventListener('load', () => {{
    drawSectorChart();
}});
window.addEventListener('resize', () => {{
    if (document.getElementById('tab-oversikt').classList.contains('active')) drawSectorChart();
}});

// Keyboard escape to close modal
document.addEventListener('keydown', e => {{
    if (e.key === 'Escape') closeModalBtn();
}});
</script>
</body>
</html>"""
    
    return html

# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    print("\n🚀 Starter porteføljeanalyse...")
    
    try:
        data = analyze_portfolio()
        html = generate_html(data)
        
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_FILE.write_text(html, encoding="utf-8")
        
        print(f"\n✅ HTML-rapport generert: {OUTPUT_FILE}")
        print(f"📊 Analyserte {len(data['portfolio'])} porteføljeaksjer")
        print(f"🔬 Minervini-screener: {data['minervini']['passed']} aksjer bestod alle kriterier")
        print("\nLast opp 'index.html' til GitHub Pages for tilgang via nettleser.")
        
    except KeyboardInterrupt:
        print("\n⏹ Avbrutt av bruker.")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Feil: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
