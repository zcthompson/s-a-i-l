# S-A-I-L — Sales Analytics and Intelligence Launchpad

Open-source workspace for sales teams to organize customer accounts, assess
AI/technology use-case readiness, score opportunities, and turn imported
pipeline and inventory data into account intelligence.

**Version:** 0.0.1 (see `VERSION`)

## Stack

- Backend: Python 3.12, FastAPI, SQLAlchemy, Alembic (SQLite by default, PostgreSQL supported)
- Frontend: React 18 + TypeScript, Vite, Vitest
- Container: multi-stage `Dockerfile`, `docker-compose.yml`

## Quick start (local)

```sh
cp .env.example .env              # fill in placeholders; set SAIL_JWT_SECRET (openssl rand -hex 32)
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
python -m backend.seed --admin-only   # bootstrap the admin user only
# or: python -m backend.seed          # fictional demo data
# or: python -m backend.seed --csv my_customers.csv   # your own customers (customer_name,rep_name,branch)
uvicorn backend.main:app --reload

cd frontend && npm ci && npm run dev
```

Customers, branches, sales teams, and users are created from scratch in the
application (admin console / import screens) or from your own CSV — no
organization data ships with the project.

## Tests

```sh
pytest -q
cd frontend && npm run lint && npm run typecheck && npm test
```

## Contributing

Run `sh scripts/setup-hooks.sh` once after cloning. The hooks and CI block
agent working folders, secrets, data exports, version drift, and
co-author/agent attribution trailers in commit messages. See `AGENTS.md`.

## License

Apache-2.0 — see [LICENSE](LICENSE).
