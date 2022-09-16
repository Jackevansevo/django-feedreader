app: gunicorn --bind 0.0.0.0:8080 feedreader.asgi:application -k uvicorn.workers.UvicornWorker
celery: celery -A feedreader worker --purge -l info -E
beat: celery -A feedreader beat -l info -S django