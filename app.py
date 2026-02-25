import os
import json
import logging
from datetime import datetime, timezone, timedelta
from flask import Flask, render_template, jsonify, request
import yfinance as yf
import requests
from bs4 import BeautifulSoup
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import schedule
import time
import threading

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

SCTR_URL = "https://stockcharts.com/freecharts/sctr.html"
SCRAPER_API = os.environ.get("SCRAPER_API_KEY", "")  # Optional: use scraper API if available
DATA_FILE = "sctr_data.json"
TAIWAN_TIMEZONE = timezone(timedelta(hours=8))

sctr_data = {"last_updated": None, "stocks": []}
is_updating = False

def get_google_sheets_client():
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        credentials = ServiceAccountCredentials.from_json_keyfile_name('google_credentials.json', scope)
        return gspread.authorize(credentials)
    except Exception as e:
        logger.error(f"Failed to initialize Google Sheets: {e}")
        return None

def scrape_sctr():
    stocks = []
    
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

def enrich_data_with_yfinance(stocks):
    enriched = []
    for stock in stocks[:50]:
        yf_data = calculate_yfinance_data(stock['symbol'])
        enriched.append({'symbol': stock['symbol'], 'sctr': stock['sctr'], **yf_data})
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
                sctr_data = json.load(f)
    except Exception as e:
        logger.error(f"Error loading data: {e}")

def export_to_google_sheets(stocks_data):
    try:
        client = get_google_sheets_client()
        if not client:
            return False, "Google Sheets client not available"
        
        try:
            spreadsheet = client.open("SCTR Rankings")
        except gspread.SpreadsheetNotFound:
            spreadsheet = client.create("SCTR Rankings")
        
        try:
            worksheet = spreadsheet.sheet1
        except:
            worksheet= spreadsheet.add_worksheet("SCTR Rankings", rows=1000, cols=10)
        
        headers = ['Symbol', 'SCTR', 'Price', 'Change', 'Change %', 'Volume', 'Market Cap', 'PE Ratio', 'Day High', 'Day Low']
        worksheet.clear()
        worksheet.append_row(headers)
        
        for stock in stocks_data:
            row = [
                stock.get('symbol', ''), stock.get('sctr', ''), stock.get('price', ''),
                stock.get('change', ''), stock.get('change_percent', ''), stock.get('volume', ''),
                stock.get('market_cap', ''), stock.get('pe_ratio', ''), stock.get('day_high', ''), stock.get('day_low', '')
            ]
            worksheet.append_row(row)
        
        return True, f"Exported {len(stocks_data)} stocks to Google Sheets"
    except Exception as e:
        logger.error(f"Error exporting to Google Sheets: {e}")
        return False, str(e)

def update_sctr_data_background():
    global sctr_data, is_updating
    is_updating = True
    
    try:
        logger.info("Starting SCTR data update...")
        stocks = scrape_sctr()
        
        if stocks:
            enriched_stocks = enrich_data_with_yfinance(stocks)
            sctr_data = {
                'last_updated': datetime.now(TAIWAN_TIMEZONE).isoformat(),
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

@app.route('/')
def index():
    load_data()
    return render_template('index.html', data=sctr_data['stocks'], last_updated=sctr_data.get('last_updated'))

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

@app.route('/api/export', methods=['POST'])
def api_export():
    load_data()
    success, message = export_to_google_sheets(sctr_data['stocks'])
    if success:
        return jsonify({'status': 'success', 'message': message})
    else:
        return jsonify({'status': 'error', 'message': message}), 500

@app.route('/api/stock/<symbol>')
def api_stock_detail(symbol):
    yf_data = calculate_yfinance_data(symbol)
    return jsonify({'symbol': symbol, **yf_data})

@app.route('/api/status')
def api_status():
    return jsonify({'is_updating': is_updating})

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
    
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
