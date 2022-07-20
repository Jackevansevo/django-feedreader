ARG PYTHON_VERSION=3.10

FROM python:${PYTHON_VERSION}-slim as base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN mkdir -p /app
WORKDIR /app

# Build dev image
FROM base as dev

RUN apt-get update && apt-get upgrade -y && apt install -y build-essential procps libpq-dev

COPY requirements.txt dev-requirements.txt .
RUN --mount=type=cache,target=~/.cache pip install -U pip && pip install -r dev-requirements.txt && pip install -r requirements.txt

COPY . .

EXPOSE 8000

CMD  ["python", "manage.py", "runserver", "0.0.0.0:8000"]

# Build prod image
FROM base as prod

ENV DEBUG=False

RUN apt update

COPY requirements.txt .
RUN --mount=type=cache,target=~/.cache pip install -U pip && pip install -r requirements.txt

COPY . .

RUN python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["gunicorn", "-b", "0.0.0.0:8000", "--workers", "2", "feedreader.wsgi"]
