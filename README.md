# SCTR Ranking Tracker

Web application for tracking StockCharts Technical Rank (SCTR) with YFinance calculations and Google Sheets export.

## Features

- Scrapes top 300 SCTR rankings from StockCharts
- Uses YFinance for additional calculations
- Export to Google Sheets
- Scheduled daily scraping at 06:00 Taiwan time
- Manual update option

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Configure Google Sheets API:
- Add credentials to `.env` file:
```
GOOGLE_SHEETS_CLIENT_ID=your_client_id
GOOGLE_SHEETS_CLIENT_SECRET=your_client_secret
GOOGLE_SHEETS_REFRESH_TOKEN=your_refresh_token
```

3. Run the application:
```bash
python app.py
```

4. Access at http://localhost:5000

## Cron Job

The scraper runs automatically at 06:00 Taiwan time daily.
