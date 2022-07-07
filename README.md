
# Running

  docker-compose up

  docker-compose exec ./manage.py migrate

# Common commands:

Django shell

  docker-compose exec app ./manage.py shell

Attach to Postgres:

  docker-compose exec app pgcli -h db -p 5432 -U postgres

Attach to redis:

  docker run --rm -it --network feedreader_default --rm redis redis-cli -h feedreader_redis_1
