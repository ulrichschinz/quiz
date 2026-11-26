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

# SEC-018 (operator follow-up, deliberately NOT done here): the container still
# runs as root. Production bind-mounts a root-owned ./quiz.db into /app/quiz.db;
# switching to an unprivileged user without first fixing the host file's owner
# would make every DB write (and the startup migration) fail. Do both together:
#   1. here:   RUN useradd --system --uid 10001 --no-create-home app \
#                && chown -R app /app
#              USER app
#   2. server: chown 10001:10001 /opt/services/quiz/quiz.db (the bind-mounted
#              file). SQLite writes its -journal/-wal next to the DB, i.e. in
#              the container's /app, which step 1 makes writable for `app`.

# Schema is migrated in-process on startup (app.core.db.create_db → Alembic).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
