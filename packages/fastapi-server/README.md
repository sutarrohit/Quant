# FastAPI Server (Supervisor)

This package is reserved for Phase 5 as the supervisor surface for the per-tenant `LiveNode`
processes and has no role in Phase 1; the previous `fastapi-blog` template domain (users/posts
routers, JWT auth, Alembic migrations, SQLite) has been stripped per D-03, leaving only a bare
FastAPI app with a `/health` endpoint until Phase 5 builds the real surface on top of it.
