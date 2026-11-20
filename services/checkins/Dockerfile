# The checkins service: Goals & Check-ins (with auth). Built once; configured only through environment
# variables and secrets, so the same image runs in compose, in CI and on Azure.

# Exact Python version (the one the code is developed and tested on), slim Debian.
FROM python:3.13.5-slim-bookworm

# No .pyc files and no pip cache in the image; log lines reach "docker logs" at once.
ENV PYTHONDONTWRITEBYTECODE=1     PYTHONUNBUFFERED=1     PIP_NO_CACHE_DIR=1     PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# The unprivileged user the service runs as (least privilege).
RUN useradd --system --uid 10001 --no-create-home app

# Dependencies before the code: a code change rebuilds only the small layers below.
# Every package is pinned, indirect ones by constraints.txt. Test tools are not installed.
COPY requirements.txt constraints.txt ./
RUN pip install --root-user-action=ignore -r requirements.txt -c constraints.txt

# Only what the service needs to run: no tests, seed, .env, .git or caches.
COPY main.py ./
COPY app/ ./app/
COPY migrations/ ./migrations/

# The commit this image was built from, shown by /health. Late, so a new commit
# doesn't invalidate the dependency layer.
ARG GIT_SHA=dev
ENV GIT_SHA=$GIT_SHA

# Files stay owned by root: the service can read its code but not change it.
USER app

# Documentation only: PORT decides the port (default 8000).
EXPOSE 8000

# Exec form: Python is process 1 and receives the stop signal. One process, so the
# migrations at startup run once; main.py binds 0.0.0.0 on PORT.
CMD ["python", "main.py"]
