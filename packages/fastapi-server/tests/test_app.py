import jwt
from httpx import AsyncClient

from config import settings


async def test_health(client: AsyncClient):
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_cors_preflight_allows_the_frontend_origin(client: AsyncClient):
    """Regression: CORS middleware was missing, so the web app could not call the API."""
    origin = settings.cors_origin_list[0]

    response = await client.options(
        "/api/posts",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


async def test_http_errors_use_the_shared_envelope(client: AsyncClient):
    body = (await client.get("/api/posts/999")).json()

    assert set(body) == {"status", "message", "path"}
    assert body["status"] == 404


async def test_openapi_has_no_malformed_paths(client: AsyncClient):
    """Regression: a missing leading slash produced the path `/api/users{user_id}`."""
    paths = (await client.get("/openapi.json")).json()["paths"]

    # A path parameter must occupy a whole segment, e.g. ".../{user_id}"
    for path in paths:
        for segment in path.split("/"):
            if "{" in segment:
                assert segment.startswith("{") and segment.endswith("}"), path

    assert "/api/users{user_id}" not in paths
    assert "/api/users/{user_id}" in paths


async def test_expired_or_invalid_token_is_rejected(client: AsyncClient):
    response = await client.get("/api/users/me", headers={"Authorization": "Bearer not-a-token"})

    assert response.status_code == 401


async def test_token_for_deleted_user_is_rejected(client: AsyncClient):
    token = jwt.encode(
        {"sub": "424242", "exp": 9999999999},
        settings.secret_key.get_secret_value(),
        algorithm=settings.algorithm,
    )

    response = await client.get("/api/users/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


async def test_default_avatar_file_is_present(client: AsyncClient):
    """image_path must resolve to a file that actually ships with the repo."""
    from config import settings

    assert (settings.media_dir / "profile_pics" / "default.svg").is_file()
