
# Running

    docker compose up -d --build

    docker compose exec ./manage.py migrate


Then visit localhost:8000

# TODO

- [x] Bleach the content to strip styling from entry
- [ ] Email for password reset
  - [ ] Find a solution for production
  - [ ] Local can probably use terminal/file email backend
- [ ] Google login / authentication
- [ ] Healthchecks for celery workers/app so they restart automatically when OOM
- [x] Search fuctionality
- [ ] Chunk / Limit uploads?
- [x] Refresh feeds button in admin?
- [ ] Admin mechanism to cancel tasks?
- [ ] Solve redis connection loss issue on redis node OOM
