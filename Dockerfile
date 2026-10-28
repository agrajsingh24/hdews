# NOTE: written but not built in the development environment (no Docker daemon / registry access).
FROM python:3.13-slim AS app
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend backend
COPY frontend/dist frontend/dist
COPY data data
COPY ml ml
COPY scripts scripts
ENV HDEWS_ENV=development DATABASE_URL=sqlite:////data/hdews.db
VOLUME /data
EXPOSE 8000
CMD ["sh", "-c", "python scripts/seed_demo_data.py 2>/dev/null || true; exec uvicorn app.main:factory --factory --app-dir backend --host 0.0.0.0 --port 8000"]
