ARG PYTHON_VERSION=3.10

FROM python:${PYTHON_VERSION}-slim as base

RUN rm -f /etc/apt/apt.conf.d/docker-clean; echo 'Binary::apt::APT::Keep-Downloaded-Packages "true";' > /etc/apt/apt.conf.d/keep-cache
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
  --mount=type=cache,target=/var/lib/apt,sharing=locked \
  apt update && apt-get --no-install-recommends install -y gcc g++ sqlite3 wget tmux

RUN mkdir -p /app
WORKDIR /app

COPY requirements.txt .
RUN --mount=type=cache,target=~/.cache pip install -U pip && pip install -r requirements.txt

COPY . .

RUN python manage.py collectstatic --noinput

EXPOSE 8080

RUN wget -O overmind.gz https://github.com/DarthSim/overmind/releases/download/v2.3.0/overmind-v2.3.0-linux-amd64.gz && gunzip overmind.gz && chmod +x overmind

CMD ["./overmind", "start"]
