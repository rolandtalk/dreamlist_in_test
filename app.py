# Version: 1.0.5
# Version: 1.0.5
import os
import json
import csv
import io
import logging
from datetime import datetime, timezone, timedelta
from flask import Flask, render_template, jsonify, request, Response
import yfinance as yf
import requests
from bs4 import BeautifulSoup
import schedule
import time
import threading

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logging.getLogger("werkzeug").setLevel(logging.WARNING)

app = Flask(__name__)

SCTR_URL = "https://stockcharts.com/freecharts/sctr.html"
SCRAPER_API = os.environ.get("SCRAPER_API_KEY", "")  # Optional: use scraper API if available
DATA_FILE = "sctr_data.json"
TAIWAN_TIMEZONE = timezone(timedelta(hours=8))

sctr_data = {"last_updated": None, "ref_qqq": {}, "stocks": []}
is_updating = False
cancel_update = False

# Session for yfinance: use curl_cffi browser impersonation if available (avoids Yahoo block)
def _make_yf_session():
    try:
        from curl_cffi import requests as curl_requests
        s = curl_requests.Session(impersonate="chrome")
        logger.info("Using curl_cffi (Chrome) for Yahoo Finance")
        return s
    except Exception as e:
        logger.warning(f"curl_cffi not available ({e}), using requests with User-Agent")
        s = requests.Session()
        s.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
        })
        return s

YF_SESSION = _make_yf_session()

def scrape_sctr():
    stocks = []
    try:
        # Method 1: Try Jina AI Reader API (free, handles JS rendering)
        try:
            jina_url = f"https://r.jina.ai/http://stockcharts.com/freecharts/sctr.html"
            response = requests.get(jina_url, timeout=30)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'lxml')
                # Try to find table data
                rows = soup.select('table tbody tr')
                if len(rows) > 5:
                    logger.info(f"Found {len(rows)} rows with Jina AI")
                    for row in rows:
                        cells = row.find_all('td')
                        if len(cells) >= 6:
                            symbol = cells[1].get_text(strip=True)
                            sctr_text = cells[5].get_text(strip=True)
                            try:
                                sctr = float(sctr_text)
                                if 0 <= sctr <= 100:
                                    stocks.append({'symbol': symbol, 'sctr': sctr})
                            except:
                                continue
                    if stocks:
                        stocks.sort(key=lambda x: x['sctr'], reverse=True)
                        return stocks[:300]
        except Exception as jina_err:
            logger.warning(f"Jina AI failed: {jina_err}")
        
        # Method 2: Try Playwright (if available)
        try:
            from playwright.sync_api import sync_playwright
            
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(SCTR_URL, wait_until="networkidle", timeout=60000)
                page.wait_for_selector("table tbody tr", timeout=30000)
                
                rows = page.query_selector_all("table tbody tr")
                logger.info(f"Found {len(rows)} rows with Playwright")
                
                for row in rows:
                    cells = row.query_selector_all("td")
                    if len(cells) >= 6:
                        symbol = cells[1].inner_text().strip()
                        sctr_text = cells[5].inner_text().strip()
                        if symbol and sctr_text:
                            try:
                                sctr_value = float(sctr_text)
                                if 0 <= sctr_value <= 100:
                                    stocks.append({'symbol': symbol, 'sctr': sctr_value})
                            except:
                                continue
                
                browser.close()
                
        except Exception as playwright_err:
            logger.warning(f"Playwright failed: {playwright_err}")
        
        # Method 3: Simple requests fallback
        if not stocks:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            response = requests.get(SCTR_URL, headers=headers, timeout=30)
            soup = BeautifulSoup(response.content, 'lxml')
            
            rows = soup.select('table tbody tr')
            for row in rows[:300]:
                cells = row.find_all('td')
                if len(cells) >= 6:
                    symbol = cells[1].get_text(strip=True)
                    sctr_text = cells[5].get_text(strip=True)
                    try:
                        sctr = float(sctr_text)
                        if 0 <= sctr <= 100:
                            stocks.append({'symbol': symbol, 'sctr': sctr})
                    except:
                        continue
        
        stocks.sort(key=lambda x: x['sctr'], reverse=True)
        logger.info(f"Scraped {len(stocks)} stocks")
        return stocks[:300]
        
    except Exception as e:
        logger.error(f"Error scraping SCTR: {e}")
        return []

def _pct_change(current, past):
    """Return percent change from past to current, or None if invalid."""
    if past is None or past == 0 or current is None:
        return None
    return round((float(current) - float(past)) / float(past) * 100, 2)

def _rsi_14(closes):
    """Compute RSI(14) from list of closes (oldest first). Needs at least 15 closes."""
    if not closes or len(closes) < 15:
        return None
    closes = [float(c) for c in closes]
    gains, losses = [], []
    for i in range(1, 15):
        ch = closes[-15 + i] - closes[-15 + i - 1]
        gains.append(ch if ch > 0 else 0)
        losses.append(-ch if ch < 0 else 0)
    avg_gain = sum(gains) / 14
    avg_loss = sum(losses) / 14
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)

def _fetch_yahoo_chart_direct(symbol, session):
    """Fetch chart data from Yahoo Finance public API. Returns list of closes or None."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=3mo&interval=1d"
    try:
        r = session.get(url, timeout=15)
        if r.status_code != 200:
            return None
        data = r.json()
        chart = data.get("chart") or data
        result_list = chart.get("result")
        if not result_list:
            return None
        result = result_list[0]
        indicators = result.get("indicators") or {}
        quote_list = indicators.get("quote")
        if not quote_list:
            return None
        quote = quote_list[0] if isinstance(quote_list, list) else quote_list
        raw = quote.get("close") or []
        closes = [float(c) for c in raw if c is not None]
        return closes if len(closes) >= 2 else None
    except Exception as e:
        logger.debug(f"Yahoo chart direct {symbol}: {e}")
        return None

def _fetch_chart_2mo(symbol, session=None):
    """Fetch ~2 months of daily chart: timestamps and closes. Returns (timestamps, closes) or (None, None)."""
    session = session or YF_SESSION
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=2mo&interval=1d"
    try:
        r = session.get(url, timeout=15)
        if r.status_code != 200:
            return None, None
        data = r.json()
        chart = data.get("chart") or data
        result_list = chart.get("result")
        if not result_list:
            return None, None
        result = result_list[0]
        ts = result.get("timestamp") or []
        indicators = result.get("indicators") or {}
        quote_list = indicators.get("quote")
        if not quote_list:
            return None, None
        quote = quote_list[0] if isinstance(quote_list, list) else quote_list
        raw = quote.get("close") or []
        closes = [float(c) if c is not None else None for c in raw]
        if not ts or len(closes) < 2:
            return None, None
        return ts, closes
    except Exception as e:
        logger.debug(f"Chart 2mo {symbol}: {e}")
        return None, None

def _ma3(closes):
    """3-day simple moving average; first two values are None."""
    out = [None, None]
    for i in range(2, len(closes)):
        if closes[i] is not None and closes[i-1] is not None and closes[i-2] is not None:
            out.append(round((closes[i] + closes[i-1] + closes[i-2]) / 3, 2))
        else:
            out.append(None)
    return out

def calculate_performance_and_rsi(symbol, session=None):
    """Compute 1D/5D/20D/60D % change, RSI(14), price, sector. Uses direct Yahoo API first (reliable), then yfinance."""
    session = session or YF_SESSION
    closes = None
    sector = ""

    # 1) Direct Yahoo Chart API first (works when yfinance is blocked)
    closes = _fetch_yahoo_chart_direct(symbol, session)

    # 2) Fallback: yfinance for history + sector
    if not closes or len(closes) < 2:
        try:
            ticker = yf.Ticker(symbol, session=session)
            hist = ticker.history(period="80d")
            if hist is not None and len(hist) >= 2:
                closes = hist["Close"].tolist()
            if not closes or len(closes) < 2:
                return {}
            info = ticker.info
            sector = (info.get("sector") or "").strip() if info else ""
        except Exception:
            return {}

    if not closes or len(closes) < 2:
        return {}

    c_now = float(closes[-1])
    perf_1d = _pct_change(c_now, closes[-2]) if len(closes) >= 2 else None
    perf_5d = _pct_change(c_now, closes[-6]) if len(closes) >= 6 else None
    perf_20d = _pct_change(c_now, closes[-21]) if len(closes) >= 21 else None
    perf_60d = _pct_change(c_now, closes[-61]) if len(closes) >= 61 else None
    rsi_14 = _rsi_14(closes)
    return {
        "perf_1d": perf_1d,
        "perf_5d": perf_5d,
        "perf_20d": perf_20d,
        "perf_60d": perf_60d,
        "rsi_14": rsi_14,
        "price": c_now,
        "sector": sector,
    }

def get_qqq_ref():
    """Get QQQ reference row: 1D, 5D, 20D, 60D. Safe when yfinance fails (e.g. rate limit)."""
    for attempt in range(2):
        try:
            data = calculate_performance_and_rsi("QQQ", session=YF_SESSION)
            if data:
                return {
                    "ref": "QQQ",
                    "perf_1d": data.get("perf_1d"),
                    "perf_5d": data.get("perf_5d"),
                    "perf_20d": data.get("perf_20d"),
                    "perf_60d": data.get("perf_60d"),
                }
        except Exception as e:
            logger.warning(f"QQQ ref attempt {attempt + 1} failed: {e}")
        time.sleep(1)
    return {"ref": "QQQ", "perf_1d": None, "perf_5d": None, "perf_20d": None, "perf_60d": None}

def calculate_yfinance_data(symbol):
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        return {
            'price': info.get('currentPrice') or info.get('regularMarketPrice'),
            'change': info.get('regularMarketChange'),
            'change_percent': info.get('regularMarketChangePercent'),
            'volume': info.get('regularMarketVolume'),
            'market_cap': info.get('marketCap'),
            'pe_ratio': info.get('trailingPE'),
            'day_high': info.get('dayHigh'),
            'day_low': info.get('dayLow'),
            'fifty_two_week_high': info.get('fiftyTwoWeekHigh'),
            'fifty_two_week_low': info.get('fiftyTwoWeekLow')
        }
    except:
        return {}

# Delay between YFinance calls to avoid Yahoo rate limiting (empty/JSON errors)
YFINANCE_DELAY_SEC = float(os.environ.get("YFINANCE_DELAY", "0.5"))
# Cap number of stocks to enrich (0 = no limit). Use e.g. 50 for faster test runs.
ENRICH_LIMIT = int(os.environ.get("ENRICH_LIMIT", "0")) or None

def enrich_data_with_yfinance(stocks):
    """Enrich stocks with 1D/5D/20D/60D and RSI(14). Stops if cancel_update is set."""
    global cancel_update
    to_process = stocks[:ENRICH_LIMIT] if ENRICH_LIMIT else stocks
    if ENRICH_LIMIT and len(stocks) > ENRICH_LIMIT:
        logger.info(f"Enriching first {ENRICH_LIMIT} of {len(stocks)} stocks (set ENRICH_LIMIT=0 for all)")
    enriched = []
    for i, stock in enumerate(to_process):
        if cancel_update:
            logger.info(f"Update cancelled after {i} stocks")
            break
        perf = calculate_performance_and_rsi(stock["symbol"], session=YF_SESSION)
        if YFINANCE_DELAY_SEC > 0:
            time.sleep(YFINANCE_DELAY_SEC)
        row = {
            "rank": i + 1,
            "symbol": stock["symbol"],
            "sctr": stock["sctr"],
            "perf_1d": perf.get("perf_1d"),
            "perf_5d": perf.get("perf_5d"),
            "perf_20d": perf.get("perf_20d"),
            "perf_60d": perf.get("perf_60d"),
            "rsi_14": perf.get("rsi_14"),
            "price": perf.get("price"),
            "sector": perf.get("sector") or "",
        }
        enriched.append(row)
        if (i + 1) % 50 == 0:
            logger.info(f"Enriched {i + 1}/{len(stocks)} stocks")
    return enriched

def save_data():
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(sctr_data, f, indent=2)
        logger.info(f"Data saved: {len(sctr_data['stocks'])} stocks")
    except Exception as e:
        logger.error(f"Error saving data: {e}")

def load_data():
    global sctr_data
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f:
                data = json.load(f)
                if isinstance(data, list):
                    sctr_data = {'last_updated': None, 'ref_qqq': {}, 'stocks': data}
                else:
                    sctr_data = data
                    if 'ref_qqq' not in sctr_data:
                        sctr_data['ref_qqq'] = {}
        else:
            sctr_data = {'last_updated': None, 'ref_qqq': {}, 'stocks': []}
    except Exception as e:
        logger.error(f"Error loading data: {e}")

def export_to_csv(stocks_data):
    """Generate CSV: RNK, SYM, 1D, 5D, 20D, 60D, RSI(14D), SCTR, Price, Sector."""
    output = io.StringIO()
    writer = csv.writer(output)
    headers = ['RNK', 'SYM', '1D', '5D', '20D', '60D', 'RSI(14D)', 'SCTR', 'Price', 'Sector']
    writer.writerow(headers)
    for stock in stocks_data:
        price = stock.get('price')
        row = [
            stock.get('rank', ''),
            stock.get('symbol', ''),
            stock.get('perf_1d') if stock.get('perf_1d') is not None else '',
            stock.get('perf_5d') if stock.get('perf_5d') is not None else '',
            stock.get('perf_20d') if stock.get('perf_20d') is not None else '',
            stock.get('perf_60d') if stock.get('perf_60d') is not None else '',
            stock.get('rsi_14') if stock.get('rsi_14') is not None else '',
            stock.get('sctr', ''),
            round(price, 2) if price is not None else '',
            stock.get('sector', '') or '',
        ]
        writer.writerow(row)
    return output.getvalue()

def update_sctr_data_background():
    global sctr_data, is_updating, cancel_update
    is_updating = True
    cancel_update = False
    try:
        logger.info("Starting SCTR data update...")
        stocks = scrape_sctr()
        if cancel_update:
            logger.info("Update cancelled before enrich")
            return
        if stocks:
            ref_qqq = get_qqq_ref()
            if cancel_update:
                logger.info("Update cancelled after QQQ")
                return
            enriched_stocks = enrich_data_with_yfinance(stocks)
            if enriched_stocks:
                sctr_data = {
                    'last_updated': datetime.now(TAIWAN_TIMEZONE).isoformat(),
                    'ref_qqq': ref_qqq,
                    'stocks': enriched_stocks
                }
                save_data()
                logger.info(f"SCTR data updated: {len(enriched_stocks)} stocks")
        else:
            logger.error("Failed to scrape SCTR data")
    except Exception as e:
        logger.error(f"Update error: {e}")
    finally:
        is_updating = False
        cancel_update = False

@app.route('/')
def index():
    load_data()
    return render_template('index.html', data=sctr_data['stocks'], last_updated=sctr_data.get('last_updated'), ref_qqq=sctr_data.get('ref_qqq') or {})

@app.route('/api/data')
def api_data():
    load_data()
    return jsonify(sctr_data)

@app.route('/api/update', methods=['POST'])
def api_update():
    global is_updating
    
    if is_updating:
        return jsonify({'status': 'processing', 'message': 'Update already in progress'}), 202
    
    thread = threading.Thread(target=update_sctr_data_background)
    thread.daemon = True
    thread.start()
    
    return jsonify({'status': 'success', 'message': 'Update started in background'})

@app.route('/api/export')
def api_export():
    """Export SCTR data as CSV file download."""
    load_data()
    csv_content = export_to_csv(sctr_data['stocks'])
    return Response(
        csv_content,
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename="dreamlist_300.csv"'}
    )

@app.route('/api/stock/<symbol>')
def api_stock_detail(symbol):
    yf_data = calculate_yfinance_data(symbol)
    return jsonify({'symbol': symbol, **yf_data})

@app.route('/api/chart/<symbol>')
def api_chart(symbol):
    """Return ~2 months of daily close, MA3, and dates for the symbol pop-up chart."""
    session = YF_SESSION
    ts, closes = _fetch_chart_2mo(symbol, session)
    if not ts or not closes or len(closes) < 2:
        return jsonify({'error': 'No chart data', 'dates': [], 'prices': [], 'ma3': []}), 404
    dates = [datetime.utcfromtimestamp(t).strftime('%Y-%m-%d') for t in ts]
    prices = [round(float(c), 2) if c is not None else None for c in closes]
    ma3 = _ma3(prices)
    current_price = prices[-1] if prices else None
    return jsonify({
        'symbol': symbol,
        'dates': dates,
        'prices': prices,
        'ma3': ma3,
        'current_price': current_price,
    })

@app.route('/api/status')
def api_status():
    return jsonify({'is_updating': is_updating})

@app.route('/api/update/cancel', methods=['POST'])
def api_update_cancel():
    global cancel_update
    cancel_update = True
    return jsonify({'status': 'ok', 'message': 'Update cancel requested'})

def run_scheduler():
    def job():
        update_sctr_data_background()
    
    schedule.every().day.at("22:00").do(job)
    
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == '__main__':
    load_data()
    
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    
    port = int(os.environ.get('PORT', 5002))
    app.run(host='0.0.0.0', port=port)
