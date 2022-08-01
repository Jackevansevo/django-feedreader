
# Running

    docker compose up -d --build

    docker compose exec ./manage.py migrate


Then visit localhost:8000

# TODO

- [x] Bleach the content to strip styling from entry
- [ ] Email for password reset
- [ ] Google login / authentication
- [ ] Healthchecks for celery workers so they're restart automatically of OOM
- [x] Search fuctionality
- [ ] Limit uploads?
- [x] Refresh feeds button in admin?
- [ ] Admin mechanism to cancel tasks?
