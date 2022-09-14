app: gunicorn --bind 0.0.0.0:8080 feedreader.asgi:application -k uvicorn.workers.UvicornWorker
celery: celery -A feedreader worker --beat --scheduler django --loglevel=info