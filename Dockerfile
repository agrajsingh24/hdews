# HDEWS: one container serves the API and the compiled frontend (same origin) and runs the background loop.
# Runtime dependencies only: the offline ML evaluation harness (scikit-learn/pandas) is NOT installed.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt \
 && useradd --system --uid 10001 --user-group --home-dir /app --no-create-home hdews \
 && mkdir -p /data && chown hdews:hdews /data

COPY backend/app backend/app
COPY frontend/dist frontend/dist
COPY data/sample data/sample
COPY scripts scripts

# Hosted demonstration by default: simulator on, strong secrets required, nothing secret printed.
# DATABASE_URL must point at persistent storage (a volume / platform disk mounted at /data).
ENV HDEWS_ENV=demo \
    DATABASE_URL=sqlite:////data/hdews.db \
    HDEWS_DOTENV=0 \
    HOST=0.0.0.0 \
    PORT=8000

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ.get('PORT', '8000'), timeout=4)"

# The entrypoint makes the SQLite directory writable, then drops to the unprivileged 'hdews' user.
ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]
CMD ["python", "scripts/start.py"]
