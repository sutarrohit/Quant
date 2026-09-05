from httpx import AsyncClient


async def test_create_post_requires_authentication(client: AsyncClient):
    response = await client.post("/api/posts", json={"title": "T", "content": "C"})

    assert response.status_code == 401


async def test_create_post(client: AsyncClient, auth_headers: dict):
    response = await client.post(
        "/api/posts",
        json={"title": "Hello", "content": "World"},
        headers=auth_headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Hello"
    assert body["user_id"] == 1
    assert body["author"]["username"] == "alice"


async def test_get_post(client: AsyncClient, auth_headers: dict):
    created = await client.post("/api/posts", json={"title": "T", "content": "C"}, headers=auth_headers)
    post_id = created.json()["id"]

    response = await client.get(f"/api/posts/{post_id}")

    assert response.status_code == 200
    assert response.json()["id"] == post_id


async def test_get_post_404(client: AsyncClient):
    response = await client.get("/api/posts/999")

    assert response.status_code == 404
    assert response.json()["message"] == "Post not found"


async def test_list_posts_pagination(client: AsyncClient, auth_headers: dict):
    for i in range(5):
        await client.post("/api/posts", json={"title": f"T{i}", "content": "C"}, headers=auth_headers)

    response = await client.get("/api/posts", params={"skip": 2, "limit": 2})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert body["limit"] == 2
    assert body["page"] == 2
    assert body["total_pages"] == 3
    assert len(body["items"]) == 2


async def test_list_posts_empty(client: AsyncClient):
    body = (await client.get("/api/posts")).json()

    assert body["total"] == 0
    assert body["total_pages"] == 0
    assert body["items"] == []


async def test_list_posts_rejects_bad_pagination(client: AsyncClient):
    assert (await client.get("/api/posts", params={"limit": 0})).status_code == 422
    assert (await client.get("/api/posts", params={"limit": 101})).status_code == 422
    assert (await client.get("/api/posts", params={"skip": -1})).status_code == 422


async def test_update_post_put(client: AsyncClient, auth_headers: dict):
    created = await client.post("/api/posts", json={"title": "T", "content": "C"}, headers=auth_headers)
    post_id = created.json()["id"]

    response = await client.put(
        f"/api/posts/{post_id}",
        json={"title": "New", "content": "Body"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["title"] == "New"


async def test_update_post_patch_is_partial(client: AsyncClient, auth_headers: dict):
    created = await client.post("/api/posts", json={"title": "T", "content": "C"}, headers=auth_headers)
    post_id = created.json()["id"]

    response = await client.patch(f"/api/posts/{post_id}", json={"title": "Patched"}, headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["title"] == "Patched"
    assert response.json()["content"] == "C"


async def test_update_other_users_post_is_forbidden(client: AsyncClient, auth_headers: dict, user_payload: dict):
    created = await client.post("/api/posts", json={"title": "T", "content": "C"}, headers=auth_headers)
    post_id = created.json()["id"]

    await client.post("/api/users", json={**user_payload, "username": "bob", "email": "bob@example.com"})
    token = (
        await client.post("/api/users/token", data={"username": "bob@example.com", "password": "password123"})
    ).json()["access_token"]

    response = await client.patch(
        f"/api/posts/{post_id}",
        json={"title": "Hacked"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


async def test_delete_post(client: AsyncClient, auth_headers: dict):
    created = await client.post("/api/posts", json={"title": "T", "content": "C"}, headers=auth_headers)
    post_id = created.json()["id"]

    response = await client.delete(f"/api/posts/{post_id}", headers=auth_headers)

    assert response.status_code == 204
    assert (await client.get(f"/api/posts/{post_id}")).status_code == 404


async def test_delete_missing_post_returns_404(client: AsyncClient, auth_headers: dict):
    """Regression: the ownership check ran before the null check and raised AttributeError."""
    response = await client.delete("/api/posts/999", headers=auth_headers)

    assert response.status_code == 404
    assert response.json()["message"] == "Post not found"
