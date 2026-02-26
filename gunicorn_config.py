import os

# Railway (and similar) set PORT; default for local
port = os.environ.get("PORT", "5001")
bind = f"0.0.0.0:{port}"
