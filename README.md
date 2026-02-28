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
python3 app.py
```
Or use the run script so the app always uses this project's data file (recommended if close prices looked wrong):
```bash
python3 run.py
```

4. Access at http://localhost:5002

## Deploy

**Render.com (free tier)**  
1. Push this repo to GitHub.  
2. Go to [dashboard.render.com](https://dashboard.render.com) → **New** → **Web Service**.  
3. Connect the repo, set **Build Command**: `pip install -r requirements.txt`, **Start Command**: `gunicorn --config gunicorn_config.py app:app`.  
4. Deploy. Render sets `PORT` automatically.

Or use the **Blueprint**: **New Blueprint Instance** → connect this repo (uses `render.yaml`).

**Railway**  
1. Push to GitHub, go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub** and select this repo.  
2. Use the existing **Procfile** (`web: gunicorn --config gunicorn_config.py app:app`). Railway sets `PORT`.

**Docker**  
```bash
docker build -t dreamlist-300 .
docker run -p 5002:5002 -e PORT=5002 dreamlist-300
```
Then open http://localhost:5002.

On first deploy the table will be empty until you click **Update** or **Refresh prices** once; on Render/Railway the filesystem is ephemeral so data does not persist across deploys unless you add a persistent disk or external storage.

## Troubleshooting: wrong close prices

- **Always run with the run script** so the app uses this project’s `sctr_data.json`:
  ```bash
  cd /path/to/dreamlist_in_test
  python3 run.py
  ```
  The script prints the data file path and MU’s price/1D% at startup; if those are correct (e.g. MU ~412, -0.77%), the server has the right data.

- **Or set the data file manually** before starting:
  ```bash
  export DREAMLIST_DATA_FILE="/full/path/to/dreamlist_in_test/sctr_data.json"
  python3 app.py
  ```

- **Refresh the table** after any code or data change: use **Refresh prices** (re-fetches close-only data for all symbols; no scrape). Wait until it finishes.

- **If the browser still shows old numbers**: use a new or incognito window, or hard-refresh (Ctrl+Shift+R). The first paint uses server-embedded data from the same file the server logged at startup.

## Cron Job

The scraper runs automatically at 06:00 Taiwan time daily.
