web: gunicorn app:app --bind 0.0.0.0:$PORT
worker: python -c "from app import run_scheduler; run_scheduler()"
