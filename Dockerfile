# S-A-I-L — Multi-stage Docker build
# Stage 1: node — install frontend deps and build the React app.
# Stage 2: python — build the FastAPI backend and serve via uvicorn.

# Stage 1: Frontend build
FROM node:24-alpine AS frontend-build

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci

COPY frontend/ .
RUN npm run build

# ── Stage 2: Backend ─────────────────────────────────────────────────────────
FROM python:3.12-slim AS backend

WORKDIR /app

# System deps for SQLite C headers
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libsqlite3-dev && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir . && \
    pip cache purge

COPY backend/ ./backend/

# Alembic migration tooling (schema upgrades inside the container)
COPY alembic/ ./alembic/
COPY alembic.ini ./

# Copy built frontend from stage 1
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# /data is the SQLite / persistent-data mount point for the single-container
# topology (SAIL_DATABASE_URL=sqlite:////data/sail.db in
# docker-compose.yml, the PVC in k8s/, sail_data in methods/docker-swarm/).
# Pre-create it owned by the app user so a freshly-created named volume / PVC
# is writable by the non-root appuser on first mount (a root-owned named volume
# would block SQLite writes).
RUN mkdir -p /data && \
    groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid 1000 --create-home appuser && \
    chown -R appuser:appuser /app /data
USER appuser

ENV PYTHONUNBUFFERED=1
ENV PORT=8000
ENV RUN_MIGRATIONS_ON_START=true

EXPOSE 8000

# Prepare persistence, optionally migrate/seed, then exec one server process.
ENTRYPOINT ["python", "-m", "backend.entrypoint"]
