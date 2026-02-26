#!/usr/bin/env python3
"""Quick check: does our session get Yahoo chart JSON?"""
from app import YF_SESSION

url = "https://query1.finance.yahoo.com/v8/finance/chart/AAPL?range=1mo&interval=1d"
r = YF_SESSION.get(url, timeout=15)
print("Status", r.status_code)
print("Content-Type", r.headers.get("content-type", ""))
if r.status_code == 200:
    d = r.json()
    has_result = bool(d and d.get("chart", {}).get("result"))
    print("Has chart result", has_result)
    if has_result:
        closes = d["chart"]["result"][0]["indicators"]["quote"][0].get("close", [])
        print("Number of closes", len([c for c in closes if c is not None]))
else:
    print("Body (first 200 chars)", (r.text or "")[:200])
