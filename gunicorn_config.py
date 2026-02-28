import os

# Railway, Render, Heroku set PORT; default for local
port = os.environ.get("PORT", "5002")
bind = f"0.0.0.0:{port}"
workers = 1
threads = 2
timeout = 120
