#!/usr/bin/env python3
"""
Oslo Børs Ticker Fetcher
========================
Henter alle noterte aksjer fra Oslo Børs automatisk via flere metoder.

Metode 1: Euronext Live AJAX-API  (krever nettleser-sesjon via Playwright)
Metode 2: stockanalysis.com        (åpen HTML, ~291 aksjer, daglig oppdatert)
Metode 3: Stoxray.com              (åpen HTML, alternativ kilde)
Metode 4: Wikipedia OSEBX          (~70 aksjer i hovedindeksen)
Metode 5: Hardkodet fallback        (~80 de største aksjene)

Bruk:
    from fetch_tickers import get_oslo_tickers
    tickers = get_oslo_tickers()  # returnerer f.eks. ["EQNR.OL", "DNB.OL", ...]

    # Kun OSEBX-komponenter (raskere):
    tickers = get_oslo_tickers(index="osebx")

    # Med Playwright (mest komplett):
    tickers = get_oslo_tickers(use_playwright=True)
"""

import re
import time
import json
import datetime
from pathlib import Path

# ─────────────────────────────────────────────────────────────
# CACHE-KONFIGURASJON
# ─────────────────────────────────────────────────────────────
CACHE_FILE = Path(__file__).parent / ".ticker_cache.json"
CACHE_TTL_HOURS = 12  # Oppdater ikke mer enn to ganger daglig


def _load_cache():
    if CACHE_FILE.exists():
        try:
            data = json.loads(CACHE_FILE.read_text())
            ts = datetime.datetime.fromisoformat(data.get("timestamp", "2000-01-01"))
            age = (datetime.datetime.now() - ts).total_seconds() / 3600
            if age < CACHE_TTL_HOURS and data.get("tickers"):
                return data["tickers"]
        except Exception:
            pass
    return None


def _save_cache(tickers: list):
    try:
        CACHE_FILE.write_text(json.dumps({
            "timestamp": datetime.datetime.now().isoformat(),
            "tickers": tickers,
            "count": len(tickers),
        }, indent=2))
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────
# HOVED-FUNKSJON
# ─────────────────────────────────────────────────────────────
def get_oslo_tickers(
    index: str = "all",
    use_playwright: bool = False,
    use_cache: bool = True,
    verbose: bool = True,
) -> list[str]:
    """
    Returnerer liste med Yahoo Finance-tickers for Oslo Børs.

    Args:
        index:          "all"   = XOSL + XOAS (alle ~290 aksjer)
                        "osebx" = Kun OSEBX-komponenter (~70 aksjer)
                        "main"  = Kun XOSL (Oslo Børs, ~180 aksjer)
        use_playwright: True = Bruk Playwright (mer komplett, krever installasjon)
        use_cache:      True = Bruk cache-fil (maks 12 timer gammel)
        verbose:        True = Print statusmeldinger

    Returns:
        list[str]: Sortert liste med tickers, f.eks. ["AKER.OL", "DNB.OL", ...]
    """
    def log(msg):
        if verbose:
            print(msg)

    # ── Cache ─────────────────────────────────────────────────
    if use_cache and index == "all":
        cached = _load_cache()
        if cached:
            log(f"  📦 Cache: {len(cached)} tickers (maks {CACHE_TTL_HOURS}t gammel)")
            return cached

    log(f"\n🔎 Henter Oslo Børs-tickers [index={index}]...")

    tickers = []

    # ── Metode 0: Playwright + Euronext (best, men trenger install) ──
    if use_playwright:
        try:
            tickers = _fetch_euronext_playwright(index, log)
            if len(tickers) >= 50:
                log(f"  ✅ Playwright/Euronext: {len(tickers)} tickers")
                if use_cache and index == "all":
                    _save_cache(tickers)
                return tickers
        except Exception as e:
            log(f"  ⚠️  Playwright feilet: {e}")

    # ── Metode 1: stockanalysis.com ───────────────────────────
    try:
        tickers = _fetch_stockanalysis(index, log)
        if len(tickers) >= 30:
            log(f"  ✅ stockanalysis.com: {len(tickers)} tickers")
            if use_cache and index == "all":
                _save_cache(tickers)
            return tickers
    except Exception as e:
        log(f"  ⚠️  stockanalysis.com feilet: {e}")

    # ── Metode 2: Stoxray.com ─────────────────────────────────
    try:
        tickers = _fetch_stoxray(log)
        if len(tickers) >= 30:
            log(f"  ✅ Stoxray: {len(tickers)} tickers")
            if use_cache and index == "all":
                _save_cache(tickers)
            return tickers
    except Exception as e:
        log(f"  ⚠️  Stoxray feilet: {e}")

    # ── Metode 3: Wikipedia OSEBX ─────────────────────────────
    try:
        tickers = _fetch_wikipedia(log)
        if len(tickers) >= 20:
            log(f"  ✅ Wikipedia: {len(tickers)} tickers")
            return tickers
    except Exception as e:
        log(f"  ⚠️  Wikipedia feilet: {e}")

    # ── Metode 4: Hardkodet fallback ──────────────────────────
    log("  ℹ️  Bruker hardkodet fallback-liste (80 aksjer)")
    return _fallback_list()


# ─────────────────────────────────────────────────────────────
# METODE 0: PLAYWRIGHT + EURONEXT LIVE
# ─────────────────────────────────────────────────────────────
def _fetch_euronext_playwright(index: str, log) -> list[str]:
    """
    Bruker Playwright til å åpne Euronext Live i en headless nettleser,
    fange opp AJAX-kallet og hente ticker-data direkte fra API-responsen.

    Installer: pip install playwright && playwright install chromium
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise ImportError(
            "Playwright ikke installert.\n"
            "Kjør: pip install playwright && playwright install chromium"
        )

    mic_map = {
        "all":    ["XOSL", "XOAS"],
        "main":   ["XOSL"],
        "osebx":  ["XOSL"],
    }
    mics = mic_map.get(index, ["XOSL", "XOAS"])

    tickers = []
    captured_responses = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
        )
        page = ctx.new_page()

        # Fang opp alle XHR/Fetch-kall som inneholder aksjedata
        def on_response(response):
            url = response.url
            if any(kw in url for kw in ["pd/data", "pd_es/data", "stocks", "equities", "getList"]):
                try:
                    body = response.body()
                    if body and b'"aaData"' in body or b'"data"' in body:
                        captured_responses.append({
                            "url": url,
                            "body": body.decode("utf-8", errors="ignore"),
                        })
                        log(f"    📡 Fanget API-kall: {url[:80]}")
                except Exception:
                    pass

        page.on("response", on_response)

        # Naviger til Oslo Børs-listen
        url = "https://live.euronext.com/en/markets/oslo/equities/list"
        log(f"    🌐 Åpner: {url}")
        page.goto(url, wait_until="networkidle", timeout=30000)

        # Vent litt ekstra for dynamisk innlasting
        page.wait_for_timeout(3000)

        # Scroll ned for å trigge lazy-loading
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2000)

        # Prøv å hente via direkte API-kall fra nettleserkonteksten
        # (har allerede sesjon/cookies fra siden)
        for mic in mics:
            for start in range(0, 500, 100):
                result = page.evaluate(f"""
                    async () => {{
                        const endpoints = [
                            '/en/pd/data/stocks?mics={mic}&start={start}&length=100',
                            '/en/pd_es/data/stocks?mics={mic}&start={start}&length=100',
                            '/en/market-data/stocks?mic={mic}&offset={start}&limit=100',
                        ];
                        for (const ep of endpoints) {{
                            try {{
                                const r = await fetch('https://live.euronext.com' + ep, {{
                                    headers: {{
                                        'X-Requested-With': 'XMLHttpRequest',
                                        'Accept': 'application/json',
                                    }}
                                }});
                                if (r.ok) {{
                                    const ct = r.headers.get('content-type') || '';
                                    if (ct.includes('json')) {{
                                        return {{ ep, data: await r.json() }};
                                    }}
                                }}
                            }} catch(e) {{}}
                        }}
                        return null;
                    }}
                """)

                if result and result.get("data"):
                    data = result["data"]
                    rows = data.get("aaData") or data.get("data") or []
                    if rows:
                        log(f"    📊 MIC {mic} start={start}: {len(rows)} rader via {result['ep']}")
                        for row in rows:
                            t = _parse_euronext_row(row)
                            if t and t not in tickers:
                                tickers.append(t)
                        if len(rows) < 100:
                            break  # Siste side
                    else:
                        break

        # Prosesser eventuelt fangede responser
        for cap in captured_responses:
            try:
                data = json.loads(cap["body"])
                rows = data.get("aaData") or data.get("data") or []
                for row in rows:
                    t = _parse_euronext_row(row)
                    if t and t not in tickers:
                        tickers.append(t)
            except Exception:
                pass

        browser.close()

    return sorted(set(tickers))


def _parse_euronext_row(row):
    """Ekstraher ticker fra en Euronext API-rad (list eller dict)."""
    cells = list(row.values()) if isinstance(row, dict) else row
    for cell in cells:
        if not isinstance(cell, str):
            continue
        # ISIN-basert ticker i URL: /en/product/equities/NO0010096985-XOSL/EQNR
        m = re.search(r'/equities?/\w+-X(?:OSL|OAS)/([A-Z0-9]{1,12})\b', cell)
        if m:
            return m.group(1) + ".OL"
        # Direkte link med ticker: href="...XOSL-EQNR..."
        m = re.search(r'[_/-]([A-Z]{2,8})-X(?:OSL|OAS)', cell)
        if m:
            return m.group(1) + ".OL"
        # Ren ticker i egen celle
        stripped = cell.strip()
        if re.fullmatch(r'[A-Z]{2,8}', stripped):
            return stripped + ".OL"
    return None


# ─────────────────────────────────────────────────────────────
# METODE 1: STOCKANALYSIS.COM
# ─────────────────────────────────────────────────────────────
def _fetch_stockanalysis(index: str, log) -> list[str]:
    """
    Scraper stockanalysis.com sin Oslo Børs-liste.
    Siden er åpen HTML — ingen autentisering nødvendig.
    Inneholder ~291 aksjer sortert etter markedsverdi.
    """
    import requests

    url = "https://stockanalysis.com/list/oslo-bors/"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "nb-NO,nb;q=0.9,en;q=0.8",
        "Referer": "https://stockanalysis.com/",
    }

    log("    🌐 Henter stockanalysis.com/list/oslo-bors/...")
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()
    html = resp.text

    # Finn alle /quote/osl/TICKER/ lenker i HTML
    # Format: <a href="/quote/osl/EQNR/">EQNR</a>
    symbols = re.findall(r'/quote/osl/([A-Z0-9]{1,12})/', html)

    if not symbols:
        raise ValueError("Ingen symboler funnet i HTML")

    seen = set()
    tickers = []
    skip_patterns = re.compile(r'^(ETF|INDEX|FUND|BOND|CERT|ETC|NOTE|XAU|XAG|USD|EUR|GBP)$')

    for sym in symbols:
        if len(sym) > 10 or skip_patterns.match(sym):
            continue
        t = sym + ".OL"
        if t not in seen:
            seen.add(t)
            tickers.append(t)

    # Filtrer til kun OSEBX hvis forespurt
    if index == "osebx":
        osebx_set = set(_osebx_components())
        tickers = [t for t in tickers if t.replace(".OL", "") in osebx_set]

    return tickers


# ─────────────────────────────────────────────────────────────
# METODE 2: STOXRAY.COM
# ─────────────────────────────────────────────────────────────
def _fetch_stoxray(log) -> list[str]:
    """
    Scraper Stoxray sin XOSL-liste.
    Alternativ kilde med komplett Oslo Børs-dekning.
    """
    import requests

    url = "https://stoxray.com/markets/xosl"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html",
    }

    log("    🌐 Henter stoxray.com/markets/xosl...")
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()
    html = resp.text

    # Finn ticker-symboler — typisk i /stock/TICKER eller /quote/TICKER lenker
    patterns = [
        r'/stock/([A-Z]{2,8})\b',
        r'/quote/([A-Z]{2,8})\b',
        r'ticker["\s:=]+["\']([A-Z]{2,8})["\']',
        r'"symbol"[:\s]+"([A-Z]{2,8})"',
    ]

    seen = set()
    tickers = []
    for pattern in patterns:
        for sym in re.findall(pattern, html):
            t = sym + ".OL"
            if t not in seen and len(sym) <= 8:
                seen.add(t)
                tickers.append(t)

    return tickers


# ─────────────────────────────────────────────────────────────
# METODE 3: WIKIPEDIA
# ─────────────────────────────────────────────────────────────
def _fetch_wikipedia(log) -> list[str]:
    """Henter OSEBX-komponenter fra Wikipedia."""
    import requests

    urls = [
        ("https://no.wikipedia.org/wiki/OBX-indeksen", r'([A-Z]{2,8})\.OL'),
        ("https://en.wikipedia.org/wiki/Oslo_Stock_Exchange", r'([A-Z]{2,8})\.OL'),
        ("https://no.wikipedia.org/wiki/Oslo_Børs_Benchmark_Index", r'([A-Z]{2,8})\.OL'),
    ]

    headers = {"User-Agent": "portfolio-analyzer/1.0 (educational use)"}

    for url, pattern in urls:
        try:
            log(f"    🌐 Prøver Wikipedia: {url.split('/')[-1]}")
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            symbols = re.findall(pattern, resp.text)
            seen = set()
            tickers = []
            for sym in symbols:
                t = sym + ".OL"
                if t not in seen:
                    seen.add(t)
                    tickers.append(t)
            if len(tickers) >= 15:
                return tickers
        except Exception as e:
            log(f"    ⚠️  {e}")

    return []


# ─────────────────────────────────────────────────────────────
# HJELPEFUNKSJON: OSEBX-KOMPONENTER (hardkodet for filter)
# ─────────────────────────────────────────────────────────────
def _osebx_components() -> list[str]:
    """Kjente OSEBX-komponenter (uten .OL) — brukes som filter."""
    return [
        "EQNR","DNB","TEL","MOWI","YAR","ORK","SALM","NHY","AKERBP","SUBC",
        "GJF","STB","FRO","WAWI","AKER","TOM","NOD","BAKKA","LSG","VEI",
        "KOG","VAR","HAUTO","ODL","KIT","TGS","DOFG","HAFNI","TIETO","AUTO",
        "PROT","MING","SPOL","SB1NO","SBNOR","SRBANK","SCATC","RECSI","SDRL",
        "PGS","PARSG","ATEA","CRAYON","BOUVET","KIT","ODL","NONG","ARCH",
    ]


# ─────────────────────────────────────────────────────────────
# METODE 4: HARDKODET FALLBACK
# ─────────────────────────────────────────────────────────────
def _fallback_list() -> list[str]:
    """80 av de største og mest likvide Oslo Børs-aksjene."""
    return [t + ".OL" for t in [
        # Large cap / OSEBX-kjerne
        "EQNR","DNB","KOG","TEL","AKERBP","NHY","YAR","GJF","MOWI","ORK",
        "VAR","AKER","SALM","SB1NO","SUBC","STB","FRO","WAWI","PROT","CMBTO",
        "AUTO","SBNOR","TOM","HAFNI","NOD","DOFG","WWI","MING","LSG","SPOL",
        "BAKKA","VEI","HAUTO","ODL","TIETO","TGS","KIT","SCATC","RECSI",
        # Mid cap
        "SRBANK","PARSG","ATEA","CRAYON","BOUVET","NONG","ARCH","BWO",
        "PGS","SDRL","AGAS","EIOF","MHG","HUNT","BONHR","SCHB","PCIB",
        "ENTRA","OLAV","ZAL","MPCC","BELCO","GOGL","OTEC","STRO","AKVA",
        "IDEX","NEXT","THIN","COOL","HEX","AUSS","FLNG","OKEA","NOG",
        "SATS","KOMPLETT","KAHOT","NORDIC","MEDI","HIDDN","VAREX","REC",
        "INSR","PROTC","HAVI","NEL","EVRY","CLOUDBERRY","HYDR","POWER",
    ]]


# ─────────────────────────────────────────────────────────────
# PRINT TICKER-LISTE (nyttig for testing)
# ─────────────────────────────────────────────────────────────
def print_tickers(tickers: list[str], columns: int = 6):
    """Print tickers i et pent rutenett."""
    print(f"\n{'─'*60}")
    print(f"  Oslo Børs — {len(tickers)} tickers")
    print(f"{'─'*60}")
    for i, t in enumerate(tickers):
        sym = t.replace(".OL", "").ljust(8)
        print(sym, end="  ")
        if (i + 1) % columns == 0:
            print()
    if len(tickers) % columns != 0:
        print()
    print(f"{'─'*60}\n")


# ─────────────────────────────────────────────────────────────
# OPPSETT-INSTRUKS FOR PLAYWRIGHT
# ─────────────────────────────────────────────────────────────
PLAYWRIGHT_INSTALL_INSTRUCTIONS = """
Installer Playwright for å bruke Euronext Live direkte:
────────────────────────────────────────────────────────
pip install playwright
playwright install chromium

Deretter i analyze_portfolio.py:
    OSEBX_TICKERS = get_oslo_tickers(use_playwright=True)
────────────────────────────────────────────────────────
Uten Playwright brukes stockanalysis.com som fallback (~291 aksjer).
"""


# ─────────────────────────────────────────────────────────────
# STANDALONE KJØRING
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    use_pw = "--playwright" in sys.argv
    idx = "osebx" if "--osebx" in sys.argv else "all"
    no_cache = "--no-cache" in sys.argv

    if use_pw:
        print(PLAYWRIGHT_INSTALL_INSTRUCTIONS)

    tickers = get_oslo_tickers(
        index=idx,
        use_playwright=use_pw,
        use_cache=not no_cache,
        verbose=True,
    )

    print_tickers(tickers)

    # Lagre til fil for inspeksjon
    out = Path(__file__).parent / "oslo_bors_tickers.txt"
    out.write_text("\n".join(tickers))
    print(f"Tickers lagret til: {out}")
