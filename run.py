#!/usr/bin/env python3
"""Run the app using this project's sctr_data.json so close prices are correct."""
import os
import sys

# Force data file to be next to this script (project root) before importing app
_script_dir = os.path.dirname(os.path.abspath(__file__))
_data_file = os.path.join(_script_dir, "sctr_data.json")
os.environ["DREAMLIST_DATA_FILE"] = _data_file

sys.path.insert(0, _script_dir)
os.chdir(_script_dir)

import app
app.load_data()
import threading
scheduler_thread = threading.Thread(target=app.run_scheduler, daemon=True)
scheduler_thread.start()
port = int(os.environ.get("PORT", "5002"))
mu = next((s for s in (app.sctr_data.get("stocks") or []) if s.get("symbol") == "MU"), None)
print("Data file:", app.DATA_FILE)
if mu:
    print("MU in data: price={} 1D%={}".format(mu.get("price"), mu.get("perf_1d")))
print("Starting on http://localhost:{}".format(port))
print("(Use this script so close prices match the data file above.)")
app.app.run(host="0.0.0.0", port=port)
