ARG PYTHON_VERSION=3.10

FROM python:${PYTHON_VERSION}-slim as base

ENV DEBUG=False

RUN apt-get update && apt-get upgrade -y && apt install -y gcc g++ sqlite3

RUN mkdir -p /app
WORKDIR /app

COPY requirements.txt .
RUN --mount=type=cache,target=~/.cache pip install -U pip && pip install -r requirements.txt

COPY . .

RUN python manage.py collectstatic --noinput

EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "feedreader.asgi:application", "-k", "uvicorn.workers.UvicornWorker"]
