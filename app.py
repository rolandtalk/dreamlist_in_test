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

# Configuration
SCTR_URL = "https://stockcharts.com/freecharts/sctr.html"
DATA_FILE = "sctr_data.json"
TAIWAN_TIMEZONE = timezone(timedelta(hours=8))

# Global data storage
sctr_data = {"last_updated": None, "stocks": []}

def get_google_sheets_client():
    """Initialize Google Sheets client"""
    try:
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]
        credentials = ServiceAccountCredentials.from_json_keyfile_name(
            'google_credentials.json', scope
        )
        return gspread.authorize(credentials)
    except Exception as e:
        logger.error(f"Failed to initialize Google Sheets: {e}")
        return None

def scrape_sctr():
    """Scrape SCTR rankings from StockCharts using Selenium on Railway"""
    stocks = []
    
    try:
        # Import selenium only when needed (works on Railway with Chrome)
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        
        # Setup Chrome options for Railway/Linux environment
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_argument('--user-agent=Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36')
        
        # Create driver
        driver = webdriver.Chrome(options=chrome_options)
        
        # Navigate to page
        driver.get(SCTR_URL)
        
        # Wait for table to load
        time.sleep(5)
        
        # Find table rows
        rows = driver.find_elements(By.CSS_SELECTOR, 'table tbody tr')
        
        for row in rows:
            cells = row.find_elements(By.CSS_SELECTOR, 'td')
            if len(cells) >= 6:
                try:
                    symbol = cells[1].text.strip()
                    sctr_text = cells[5].text.strip()
                    
                    if symbol and sctr_text:
                        try:
                            sctr_value = float(sctr_text)
                            stocks.append({
                                'symbol': symbol,
                                'sctr': sctr_value
                            })
                        except ValueError:
                            continue
                except Exception:
                    continue
        
        driver.quit()
        
        # Sort by SCTR rank and take top 300
        stocks.sort(key=lambda x: x['sctr'], reverse=True)
        stocks = stocks[:300]
        
        logger.info(f"Scraped {len(stocks)} stocks from SCTR")
        return stocks
        
    except ImportError:
        logger.warning("Selenium not available, using requests fallback")
        return scrape_sctr_fallback()
    except Exception as e:
        logger.error(f"Error scraping SCTR with Selenium: {e}")
        return scrape_sctr_fallback()

def scrape_sctr_fallback():
    """Fallback: Simple requests without JS rendering"""
    stocks = []
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(SCTR_URL, headers=headers, timeout=30)
        soup = BeautifulSoup(response.content, 'lxml')
        
        # Try to find any table data
        rows = soup.select('table tbody tr')
        for row in rows[:300]:
            cells = row.find_all('td')
            if len(cells) >= 6:
                symbol = cells[1].get_text(strip=True)
                sctr_text = cells[5].get_text(strip=True)
                try:
                    sctr = float(sctr_text)
                    stocks.append({'symbol': symbol, 'sctr': sctr})
                except:
                    continue
        
        logger.info(f"Fallback scraped {len(stocks)} stocks")
        return stocks[:300]
    except Exception as e:
        logger.error(f"Fallback also failed: {e}")
        return []

def calculate_yfinance_data(symbol):
    """Calculate additional data using YFinance"""
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
    except Exception as e:
        logger.warning(f"Error fetching YFinance data for {symbol}: {e}")
        return {}

def enrich_data_with_yfinance(stocks):
    """Enrich stock data with YFinance calculations"""
    enriched = []
    for stock in stocks[:50]:
        yf_data = calculate_yfinance_data(stock['symbol'])
        enriched.append({
            'symbol': stock['symbol'],
            'sctr': stock['sctr'],
            **yf_data
        })
    return enriched

def save_data():
    """Save data to JSON file"""
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(sctr_data, f, indent=2)
        logger.info(f"Data saved: {len(sctr_data['stocks'])} stocks")
    except Exception as e:
        logger.error(f"Error saving data: {e}")

def load_data():
    """Load data from JSON file"""
    global sctr_data
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f:
                sctr_data = json.load(f)
    except Exception as e:
        logger.error(f"Error loading data: {e}")

def export_to_google_sheets(stocks_data):
    """Export stock data to Google Sheets"""
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
            worksheet = spreadsheet.add_worksheet("SCTR Rankings", rows=1000, cols=10)
        
        headers = ['Symbol', 'SCTR', 'Price', 'Change', 'Change %', 'Volume', 'Market Cap', 'PE Ratio', 'Day High', 'Day Low']
        
        worksheet.clear()
        worksheet.append_row(headers)
        
        for stock in stocks_data:
            row = [
stock.get('symbol', ''),
                stock.get('sctr', ''),
                stock.get('price', ''),
                stock.get('change', ''),
                stock.get('change_percent', ''),
                stock.get('volume', ''),
                stock.get('market_cap', ''),
                stock.get('pe_ratio', ''),
                stock.get('day_high', ''),
                stock.get('day_low', '')
            ]
            worksheet.append_row(row)
        
        return True, f"Exported {len(stocks_data)} stocks to Google Sheets"
    except Exception as e:
        logger.error(f"Error exporting to Google Sheets: {e}")
        return False, str(e)

def update_sctr_data():
    """Update SCTR data - main function"""
    global sctr_data
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
        return True
    else:
        logger.error("Failed to scrape SCTR data")
        return False

def run_scheduler():
    """Run scheduled tasks"""
    def job():
        update_sctr_data()
    
    # Schedule at 06:00 Taiwan time daily
    schedule.every().day.at("22:00").do(job)
    
    while True:
        schedule.run_pending()
        time.sleep(60)

# Routes
@app.route('/')
def index():
    """Main page"""
    load_data()
    return render_template('index.html', 
                          data=sctr_data['stocks'], 
                          last_updated=sctr_data.get('last_updated'))

@app.route('/api/data')
def api_data():
    """API endpoint for stock data"""
    load_data()
    return jsonify(sctr_data)

@app.route('/api/update', methods=['POST'])
def api_update():
    """Manual update endpoint"""
    success = update_sctr_data()
    if success:
        return jsonify({'status': 'success', 'message': 'Data updated successfully'})
    else:
        return jsonify({'status': 'error', 'message': 'Failed to update data'}), 500

@app.route('/api/export', methods=['POST'])
def api_export():
    """Export to Google Sheets endpoint"""
    load_data()
    success, message = export_to_google_sheets(sctr_data['stocks'])
    if success:
        return jsonify({'status': 'success', 'message': message})
    else:
        return jsonify({'status': 'error', 'message': message}), 500

@app.route('/api/stock/<symbol>')
def api_stock_detail(symbol):
    """Get detailed info for a single stock"""
    yf_data = calculate_yfinance_data(symbol)
    return jsonify({'symbol': symbol, **yf_data})

if __name__ == '__main__':
    load_data()
    
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
