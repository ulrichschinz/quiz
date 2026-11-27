FROM python:3.12-slim

WORKDIR /app

# Hash-pinned lockfile (SEC-019): every package, including transitive ones, is
# verified against its sha256. Regenerate with `make lock` after editing
# requirements.txt.
COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

# App source (app/, templates/, static/ incl. vendored brand, migrations/, scripts/).
# .dockerignore keeps .env, *.db, .venv, .git, docs/ and tests/ out of the image.
COPY . .

EXPOSE 8000

# SEC-003/007: the per-IP submit and login throttles key on the client address
# uvicorn reports. The reverse proxy (Caddy in the repo compose, Traefik in
# production) runs in another container, so uvicorn must trust its
# X-Forwarded-For — otherwise every visitor shares the proxy's bucket and 10
# submits/min would throttle the whole site. uvicorn reads this variable itself
# (CIDRs allowed) and takes the right-most untrusted X-Forwarded-For entry, i.e.
# the address the proxy saw. Default: loopback + the private ranges Docker
# networks use; the app port is only reachable via the proxy network (compose
# binds it to 127.0.0.1). Narrow it via .env to the proxy network's subnet, e.g.
# `docker network inspect traefik-public -f '{{(index .IPAM.Config 0).Subnet}}'`.
ENV FORWARDED_ALLOW_IPS="127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"

# SEC-018: run unprivileged. The source tree stays root-owned and read-only for
# the app user; only /app/data is writable. Production bind-mounts the lead DB
# as /app/data/quiz.db (host file owned 10001:0, mode 660) and SQLite writes its
# rollback journal next to it, inside /app/data.
ENV PYTHONDONTWRITEBYTECODE=1 \
    DATABASE_URL=sqlite:////app/data/quiz.db
RUN python -m compileall -q app codeindex migrations \
    && useradd --system --uid 10001 --gid 0 --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/data \
    && chown 10001:0 /app/data \
    && chmod 2770 /app/data
USER 10001

# Schema is migrated in-process on startup (app.core.db.create_db → Alembic).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
