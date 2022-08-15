ARG PYTHON_VERSION=3.11-rc

FROM python:${PYTHON_VERSION}-slim as base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

RUN mkdir -p /app
WORKDIR /app

# Build dev image
FROM base as dev

RUN apt-get update && apt-get upgrade -y && apt install -y gcc g++ procps libpq-dev telnet rlwrap

COPY requirements.txt dev-requirements.txt .
RUN --mount=type=cache,target=~/.cache pip install -U pip && pip install -r dev-requirements.txt && pip install -r requirements.txt

COPY . .

RUN python manage.py collectstatic --noinput

EXPOSE 8000


CMD  ["python", "manage.py", "runserver", "0.0.0.0:8000"]

# Build prod image
FROM base as prod

ENV DEBUG=False

RUN apt-get update && apt-get upgrade -y && apt install -y gcc g++ libpq-dev

COPY requirements.txt .
RUN --mount=type=cache,target=~/.cache pip install -U pip && pip install -r requirements.txt

COPY . .

RUN python manage.py collectstatic --noinput

EXPOSE 8000
