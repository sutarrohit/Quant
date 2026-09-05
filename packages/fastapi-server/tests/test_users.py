import base64

import pytest
from httpx import AsyncClient


async def test_create_user(client: AsyncClient, user_payload: dict):
    response = await client.post("/api/users", json=user_payload)

    assert response.status_code == 201
    body = response.json()
    assert body["username"] == "alice"
    assert body["email"] == "alice@example.com"
    assert "password" not in body
    assert "password_hash" not in body


async def test_create_user_normalises_email(client: AsyncClient, user_payload: dict):
    response = await client.post("/api/users", json={**user_payload, "email": "Alice@Example.COM"})

    assert response.status_code == 201
    assert response.json()["email"] == "alice@example.com"


@pytest.mark.parametrize(
    ("field", "value"),
    [("username", "alice"), ("email", "alice@example.com")],
)
async def test_create_user_rejects_duplicates(client: AsyncClient, user_payload: dict, field: str, value: str):
    await client.post("/api/users", json=user_payload)

    duplicate = {**user_payload, "username": "bob", "email": "bob@example.com", field: value}
    response = await client.post("/api/users", json=duplicate)

    assert response.status_code == 400


async def test_create_user_rejects_short_password(client: AsyncClient, user_payload: dict):
    response = await client.post("/api/users", json={**user_payload, "password": "short"})

    assert response.status_code == 422
    assert response.json()["message"] == "Validation error"


async def test_login_returns_token(client: AsyncClient, user_payload: dict):
    await client.post("/api/users", json=user_payload)

    response = await client.post(
        "/api/users/token",
        data={"username": user_payload["email"], "password": user_payload["password"]},
    )

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert response.json()["access_token"]


async def test_login_rejects_bad_password(client: AsyncClient, user_payload: dict):
    await client.post("/api/users", json=user_payload)

    response = await client.post(
        "/api/users/token",
        data={"username": user_payload["email"], "password": "wrong-password"},
    )

    assert response.status_code == 401


async def test_me_requires_authentication(client: AsyncClient):
    assert (await client.get("/api/users/me")).status_code == 401


async def test_me_returns_current_user(client: AsyncClient, auth_headers: dict):
    response = await client.get("/api/users/me", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["username"] == "alice"


async def test_me_is_not_parsed_as_a_user_id(client: AsyncClient, auth_headers: dict):
    """`/me` is declared before `/{user_id}`, so it must not 422 as an int path."""
    response = await client.get("/api/users/me", headers=auth_headers)
    assert response.status_code == 200


async def test_get_user_returns_a_user_not_a_post(client: AsyncClient, auth_headers: dict):
    """Regression: this route previously returned a Post object."""
    await client.post("/api/posts", json={"title": "T", "content": "C"}, headers=auth_headers)

    response = await client.get("/api/users/1")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 1
    assert body["username"] == "alice"
    assert "title" not in body
    assert "content" not in body


async def test_get_user_404(client: AsyncClient):
    assert (await client.get("/api/users/999")).status_code == 404


async def test_list_users_pagination(client: AsyncClient, user_payload: dict):
    for i in range(3):
        await client.post(
            "/api/users",
            json={**user_payload, "username": f"user{i}", "email": f"user{i}@example.com"},
        )

    response = await client.get("/api/users", params={"skip": 0, "limit": 2})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["total_pages"] == 2
    assert body["page"] == 1
    assert len(body["items"]) == 2


async def test_update_user(client: AsyncClient, auth_headers: dict):
    response = await client.patch("/api/users/1", json={"username": "alice2"}, headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["username"] == "alice2"


async def test_update_other_user_is_forbidden(client: AsyncClient, auth_headers: dict, user_payload: dict):
    await client.post("/api/users", json={**user_payload, "username": "bob", "email": "bob@example.com"})

    response = await client.patch("/api/users/2", json={"username": "hacked"}, headers=auth_headers)

    assert response.status_code == 403


async def test_delete_user_cascades_to_posts(client: AsyncClient, auth_headers: dict):
    await client.post("/api/posts", json={"title": "T", "content": "C"}, headers=auth_headers)

    response = await client.delete("/api/users/1", headers=auth_headers)

    assert response.status_code == 204
    assert (await client.get("/api/posts")).json()["total"] == 0


async def test_get_user_posts(client: AsyncClient, auth_headers: dict):
    await client.post("/api/posts", json={"title": "T", "content": "C"}, headers=auth_headers)

    response = await client.get("/api/users/1/posts")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["author"]["username"] == "alice"


async def test_default_avatar_is_served_under_the_media_mount(client: AsyncClient, auth_headers: dict):
    """Regression: image_path used to point at an unmounted /static prefix."""
    response = await client.get("/api/users/me", headers=auth_headers)

    assert response.json()["image_path"].startswith("/media/")


async def test_avatar_upload_replaces_the_default(client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "media_dir", tmp_path)

    # Smallest valid PNG: a single transparent pixel
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
        "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
    )

    response = await client.post(
        "/api/users/me/avatar",
        files={"file": ("avatar.png", png, "image/png")},
        headers=auth_headers,
    )

    assert response.status_code == 200
    image_file = response.json()["image_file"]
    assert image_file is not None
    assert response.json()["image_path"] == f"/media/profile_pics/{image_file}"
    assert (tmp_path / "profile_pics" / image_file).exists()


async def test_avatar_upload_rejects_non_images(client: AsyncClient, auth_headers: dict, tmp_path, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "media_dir", tmp_path)

    response = await client.post(
        "/api/users/me/avatar",
        files={"file": ("payload.txt", b"not an image", "text/plain")},
        headers=auth_headers,
    )

    assert response.status_code == 400


async def test_avatar_upload_requires_authentication(client: AsyncClient):
    response = await client.post("/api/users/me/avatar", files={"file": ("a.png", b"x", "image/png")})

    assert response.status_code == 401
