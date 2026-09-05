# FastAPI Server

A blog API template: JWT auth, async SQLAlchemy 2.0, Alembic migrations and a pytest suite.
It is the Python counterpart to `apps/server` (Hono + Prisma) in this monorepo — use whichever
backend suits the project and delete the other.

## Stack

| Concern    | Choice                                  |
| ---------- | --------------------------------------- |
| Framework  | FastAPI                                 |
| ORM        | SQLAlchemy 2.0 (async, `Mapped[]`)      |
| Database   | SQLite via `aiosqlite` (swap the URL)   |
| Migrations | Alembic (async template, batch mode)    |
| Auth       | OAuth2 password flow, JWT, argon2 hashes|
| Packaging  | uv                                      |
| Tests      | pytest + pytest-asyncio + httpx         |
| Lint       | ruff                                    |

## Quick start

```bash
cd packages/fastapi-server

uv sync                                  # install dependencies
cp .env.example .env                     # then set SECRET_KEY
sed -i "s/^SECRET_KEY=.*/SECRET_KEY=$(openssl rand -hex 32)/" .env

uv run alembic upgrade head              # create the schema
uv run python -m scripts.seed            # optional demo data
uv run fastapi dev main.py               # http://127.0.0.1:8000/docs
```

The API has no landing page — Swagger is the entry point.

- Swagger UI: <http://127.0.0.1:8000/docs>
- ReDoc: <http://127.0.0.1:8000/redoc>
- Health: <http://127.0.0.1:8000/health>

Seeded accounts log in with the password `password123`.

### From the monorepo root

The package exposes a `package.json`, so Turborepo drives it alongside the Node apps:

```bash
pnpm dev     # runs web + both servers
pnpm test    # runs every workspace test suite
pnpm lint
```

## Configuration

All settings are read from `.env` (see `.env.example`). Environment variables take precedence
over the file, which is what CI and containers rely on.

| Variable                      | Default                        | Notes                                             |
| ----------------------------- | ------------------------------ | ------------------------------------------------- |
| `SECRET_KEY`                  | **required**                   | JWT signing key; the app refuses to start without it |
| `ALGORITHM`                   | `HS256`                        | JWT algorithm                                     |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30`                           | Token lifetime                                    |
| `ENVIRONMENT`                 | `development`                  | `development` runs `create_all` on startup        |
| `DATABASE_URL`                | `sqlite+aiosqlite:///./blog.db`| Any SQLAlchemy **async** URL                      |
| `CORS_ORIGINS`                | `localhost:3000,localhost:5173`| Comma-separated allowed origins                   |

### Switching to PostgreSQL

```bash
uv add asyncpg
# .env
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/blog
```

Then `uv run alembic upgrade head`. No application code changes are needed — the engine is built
from `settings.database_url`.

## API

| Method   | Path                     | Auth | Description                          |
| -------- | ------------------------ | ---- | ------------------------------------ |
| `GET`    | `/health`                | –    | Liveness probe                       |
| `POST`   | `/api/users`             | –    | Register                             |
| `POST`   | `/api/users/token`       | –    | Log in (form body), returns a JWT    |
| `GET`    | `/api/users`             | –    | List users (paginated)               |
| `GET`    | `/api/users/me`          | ✓    | Current user                         |
| `POST`   | `/api/users/me/avatar`   | ✓    | Upload a profile picture (≤ 2 MB)    |
| `GET`    | `/api/users/{id}`        | –    | Public profile                       |
| `GET`    | `/api/users/{id}/posts`  | –    | That user's posts                    |
| `PATCH`  | `/api/users/{id}`        | ✓    | Update yourself                      |
| `DELETE` | `/api/users/{id}`        | ✓    | Delete yourself (cascades to posts)  |
| `GET`    | `/api/posts`             | –    | List posts (paginated)               |
| `POST`   | `/api/posts`             | ✓    | Create a post                        |
| `GET`    | `/api/posts/{id}`        | –    | Read a post                          |
| `PUT`    | `/api/posts/{id}`        | ✓    | Replace a post you own               |
| `PATCH`  | `/api/posts/{id}`        | ✓    | Update fields on a post you own      |
| `DELETE` | `/api/posts/{id}`        | ✓    | Delete a post you own                |

Uploaded files are served from `/media`. The login endpoint follows the OAuth2 password flow, so
the form field is named `username` but carries the user's **email**.

### Example

```bash
curl -X POST localhost:8000/api/users \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","email":"alice@example.com","password":"password123"}'

TOKEN=$(curl -s -X POST localhost:8000/api/users/token \
  -d 'username=alice@example.com&password=password123' | jq -r .access_token)

curl -X POST localhost:8000/api/posts \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"title":"Hello","content":"World"}'
```

### Error shape

Every `HTTPException` is returned through one envelope:

```json
{ "status": 404, "message": "Post not found", "path": "http://localhost:8000/api/posts/999" }
```

Validation failures return `422` with an additional `errors` array.

## Migrations

```bash
uv run alembic upgrade head                          # apply
uv run alembic revision --autogenerate -m "message"  # create after editing db/models.py
uv run alembic downgrade -1                          # roll back one
```

`alembic/env.py` reads the URL from `config.settings`, so `alembic.ini` holds no credentials.
`render_as_batch=True` is enabled so column changes also work on SQLite.

## Tests

```bash
uv run pytest          # 55 tests
uv run pytest -v
```

Each test gets a fresh in-memory SQLite database via the `db_session` fixture, injected into the
app with `dependency_overrides`. The `auth_headers` fixture registers a user and returns a bearer
header. Tests never touch `blog.db` or your `.env`.

## Docker

```bash
docker build -t fastapi-server .
docker run -p 8000:8000 -e SECRET_KEY=$(openssl rand -hex 32) fastapi-server
```

The image is a two-stage uv build that runs as a non-root user and ships a `/health` healthcheck.
Run migrations against your database before starting the container in production.

## Layout

```
├── main.py              # app, CORS, mounts, exception handlers
├── config.py            # pydantic-settings, reads .env
├── auth.py              # hashing, JWT, CurrentUser dependency
├── exceptions.py        # NotFoundError, ConflictError, PermissionDeniedError...
├── alembic/             # migration environment and versions
├── db/
│   ├── database.py      # engine, session factory, get_db
│   └── models.py        # User, Post
├── routers/             # HTTP layer: paths, status codes, response models
├── service/             # business logic, raises domain errors
│   ├── user_service.py
│   └── post_service.py
├── schema/              # pydantic request/response models
├── scripts/seed.py      # demo data
├── tests/               # pytest suite
└── media/               # uploads, served at /media
```

## Architecture

Requests flow in one direction:

```
routers/  ->  service/  ->  db/
  HTTP        rules       SQLAlchemy
```

**Routers** own everything HTTP: the path, the status code, the `response_model`,
and the auth dependency. They contain no queries and no rules — each handler is a
line or two that delegates and returns.

**Services** own the rules: uniqueness checks, ownership checks, upload limits,
pagination queries. They take a session and plain arguments, and they never import
FastAPI. When something is wrong they raise a domain error from
`exceptions.py` rather than an `HTTPException`:

```python
async def delete_post(db, post_id, current_user):
    post = await get_post(db, post_id)          # raises NotFoundError
    _assert_owner(post, current_user, "delete") # raises PermissionDeniedError
    await db.delete(post)
    await db.commit()
```

`main.py` registers one handler that turns any `ServiceError` into the standard
JSON envelope, using the `status_code` declared on the error class. Adding a new
error type means adding a class in `exceptions.py`, not touching every router.

Because services have no HTTP dependency, they are callable from scripts, workers
and tests. `tests/test_service.py` exercises the rules directly:

```python
with pytest.raises(PermissionDeniedError):
    await post_service.update_post(db_session, post.id, PostUpdate(title="Hacked"), bob)
```

## Notes

- `create_all` runs on startup only when `ENVIRONMENT=development`; production relies on Alembic.
- Tokens carry the user id in `sub` and are validated with `require: ["exp", "sub"]`.
- Login does not reveal whether the email or the password was wrong.
- There is no refresh-token flow or rate limiting — add both before real use.
