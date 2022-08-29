# !/usr/bin/env sh
python manage.py makemigrations
python manage.py makemigrations feeds
python manage.py migrate
