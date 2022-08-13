
# Running

    docker compose up -d --build

The application expects a file called `secrets.env` in the project root with the following variables:

    GOOGLE_CLIENT_ID=XYZ
    GOOGLE_CLIENT_SECRET=XYZ

Mmake/run the migrations:

    docker compose exec ./manage.py makemigrations

    docker compose exec ./manage.py migrate


Create a superuser/root/administrator account:

    docker compose exec app ./manage.py createsuperuser

Then visit localhost:8000

# TODO

- [x] Automatically find rss feed for a given URL
  - Fetch the raw site content, use beautiful soup to find links
  - Fall back to naively querying /index.xml /rss /feed /rss.xml /feed.xml if this fails
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
- [ ] Some entries might not have links, in which case hide the link
