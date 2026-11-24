import httpx
from fastapi import Depends, FastAPI, Header

from enacit4r_contrib.identity import github_reviewer, keycloak_github_login
from enacit4r_contrib.testing import FakeRepo


class CountingRepo(FakeRepo):
    calls: int = 0

    async def permission(self, login):
        self.calls += 1
        return await super().permission(login)


def make(repo, minimum="write"):
    def login(x_login: str | None = Header(None)):
        return x_login

    app = FastAPI()

    @app.get("/r")
    async def r(who: str = Depends(github_reviewer(repo, login, minimum=minimum))):
        return {"who": who}

    return httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://t")


async def test_reviewer_needs_a_login_and_write_access():
    repo = FakeRepo(permissions={"r": "read", "w": "write", "a": "admin"})
    client = make(repo)
    assert (await client.get("/r")).status_code == 401
    assert (await client.get("/r", headers={"x-login": "r"})).status_code == 403
    assert (await client.get("/r", headers={"x-login": "nobody"})).status_code == 403
    for who in ("w", "a"):
        r = await client.get("/r", headers={"x-login": who})
        assert r.status_code == 200 and r.json() == {"who": who}


async def test_reviewer_caches_the_permission():
    repo = CountingRepo(permissions={"w": "write"})
    client = make(repo)
    for _ in range(2):
        assert (await client.get("/r", headers={"x-login": "w"})).status_code == 200
    assert repo.calls == 1


async def test_keycloak_github_login_reads_the_claim():
    payloads = {"a": {"github_login": "ada"}, "b": {"sub": "x"}}

    def get_payload(token: str | None = Header(None)):
        return payloads.get(token)

    app = FastAPI()

    @app.get("/me")
    def me(login: str | None = Depends(keycloak_github_login(get_payload))):
        return {"login": login}

    client = httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://t")
    for token, expected in (("a", "ada"), ("b", None), ("none", None)):
        r = await client.get("/me", headers={"token": token})
        assert r.json() == {"login": expected}
