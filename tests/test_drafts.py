from datetime import date

import httpx
import pytest
from fastapi import FastAPI, Header, HTTPException

from enacit4r_contrib import Contributor, Issue, Pipeline, Report, contribution_router
from enacit4r_contrib.drafts import (
    Draft,
    DraftSink,
    FolderDraftStore,
    Review,
    State,
    TransitionError,
    review_router,
)

PERSON = {"name": "Ada Lovelace", "email": "ada@example.org", "institution": "EPFL"}
BUNDLE = {"a.csv": b"a,b\n1,2\n", "sub/b.csv": b"x\n"}


async def validate(bundle):
    return [Issue("odd", file="a.csv", severity="warning")] if "a.csv" in bundle else []


def client_for(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://t")


async def submitted(store):
    sink = DraftSink(store, today=lambda: date(2026, 11, 19))
    report = Report([Issue("odd", file="a.csv", severity="warning")])
    receipt = await sink.submit(BUNDLE, Contributor(**PERSON), report)
    return receipt.id


async def test_pattern_a_end_to_end(tmp_path):
    store = FolderDraftStore(tmp_path)
    sink = DraftSink(store)
    app = FastAPI()
    app.include_router(contribution_router(Pipeline(validate, sink), allow=["*.csv"]))
    up = [("files", ("a.csv", b"a,b\n1,2\n", "text/csv"))]
    r = await client_for(app).post("/contributions", data=PERSON, files=up)
    assert r.status_code == 201, r.text
    assert r.json()["url"] == ""
    draft = await store.load(r.json()["id"])
    assert draft.state == State.SUBMITTED and draft.files == ["a.csv"]
    assert draft.report.issues[0].message == "odd"
    assert await store.files(draft.id) == {"a.csv": b"a,b\n1,2\n"}
    assert await sink.open_count() == 1


async def test_id_format(tmp_path):
    id_ = await submitted(FolderDraftStore(tmp_path))
    assert id_.startswith("2026-11-19-ada-lovelace-") and len(id_.split("-")[-1]) == 6


async def test_accept_then_publish(tmp_path):
    store = FolderDraftStore(tmp_path)
    id_ = await submitted(store)
    published, changes = [], []

    async def on_publish(draft, files):
        published.append((draft.id, files))

    async def on_change(draft, decision):
        changes.append(decision.state)

    review = Review(store, on_publish=on_publish, on_change=on_change)
    await review.decide(id_, State.ACCEPTED, "bob")
    draft = await review.decide(id_, State.PUBLISHED, "carol")
    assert published == [(id_, BUNDLE)]
    assert [(d.state, d.by) for d in draft.history] == [
        (State.ACCEPTED, "bob"),
        (State.PUBLISHED, "carol"),
    ]
    assert (await store.load(id_)).state == State.PUBLISHED
    assert changes == [State.ACCEPTED, State.PUBLISHED]
    assert await DraftSink(store).open_count() == 0


async def test_publish_from_submitted_is_refused(tmp_path):
    store = FolderDraftStore(tmp_path)
    id_ = await submitted(store)
    with pytest.raises(TransitionError):
        await Review(store).decide(id_, State.PUBLISHED, "bob")


async def test_reject_needs_a_comment(tmp_path):
    store = FolderDraftStore(tmp_path)
    id_ = await submitted(store)
    with pytest.raises(ValueError):
        await Review(store).decide(id_, State.REJECTED, "bob", " ")
    draft = await Review(store).decide(id_, State.REJECTED, "bob", "wrong units")
    assert draft.history[0].comment == "wrong units"


async def test_failing_on_publish_leaves_the_draft_accepted(tmp_path):
    store = FolderDraftStore(tmp_path)
    id_ = await submitted(store)
    changes = []

    async def broken(draft, files):
        raise RuntimeError("database down")

    async def on_change(draft, decision):
        changes.append(decision.state)

    review = Review(store, on_publish=broken, on_change=on_change)
    await review.decide(id_, State.ACCEPTED, "bob")
    with pytest.raises(RuntimeError):
        await review.decide(id_, State.PUBLISHED, "bob")
    draft = await store.load(id_)
    assert draft.state == State.ACCEPTED and len(draft.history) == 1
    assert changes == [State.ACCEPTED]


def admin(x_user: str | None = Header(default=None)) -> str:
    if x_user is None:
        raise HTTPException(401, "Log in")
    return x_user


async def router_client(tmp_path, on_publish=None):
    store = FolderDraftStore(tmp_path)
    id_ = await submitted(store)
    app = FastAPI()
    app.include_router(
        review_router(Review(store, on_publish=on_publish), reviewer=admin)
    )
    client = client_for(app)
    client.headers["X-User"] = "bob"
    return client, id_


async def test_router_list_and_decide(tmp_path):
    client, id_ = await router_client(tmp_path)
    r = await client.get("/drafts", params={"state": "submitted"})
    assert [d["id"] for d in r.json()] == [id_]
    assert (await client.get("/drafts", params={"state": "accepted"})).json() == []
    r = await client.post(f"/drafts/{id_}/decision", json={"state": "accepted"})
    assert r.status_code == 200 and r.json()["state"] == "accepted"
    assert r.json()["history"][0]["by"] == "bob"
    assert (await client.get(f"/drafts/{id_}")).json()["state"] == "accepted"


async def test_router_refuses_without_reviewer(tmp_path):
    client, id_ = await router_client(tmp_path)
    del client.headers["X-User"]
    assert (await client.get("/drafts")).status_code == 401
    r = await client.post(f"/drafts/{id_}/decision", json={"state": "accepted"})
    assert r.status_code == 401


async def test_router_errors(tmp_path):
    client, id_ = await router_client(tmp_path)
    r = await client.post(f"/drafts/{id_}/decision", json={"state": "published"})
    assert r.status_code == 409 and "Cannot go" in r.json()["detail"]
    r = await client.post(f"/drafts/{id_}/decision", json={"state": "rejected"})
    assert r.status_code == 422
    assert (await client.get("/drafts/nope")).status_code == 404
    assert (await client.get("/drafts/..")).status_code == 404
    r = await client.post("/drafts/nope/decision", json={"state": "accepted"})
    assert r.status_code == 404
    assert (await client.get(f"/drafts/{id_}/files/none.csv")).status_code == 404


async def test_router_file_download(tmp_path):
    client, id_ = await router_client(tmp_path)
    r = await client.get(f"/drafts/{id_}/files/sub/b.csv")
    assert r.status_code == 200 and r.content == b"x\n"
    assert r.headers["content-type"] == "application/octet-stream"


async def test_router_failing_publish_is_502(tmp_path):
    async def broken(draft, files):
        raise RuntimeError("database down")

    client, id_ = await router_client(tmp_path, on_publish=broken)
    await client.post(f"/drafts/{id_}/decision", json={"state": "accepted"})
    r = await client.post(f"/drafts/{id_}/decision", json={"state": "published"})
    assert r.status_code == 502 and "stays accepted" in r.json()["detail"]
    assert (await client.get(f"/drafts/{id_}")).json()["state"] == "accepted"


async def test_store_refuses_unsafe_ids(tmp_path):
    store = FolderDraftStore(tmp_path / "drafts")
    draft = Draft("../x", State.SUBMITTED, Contributor(**PERSON), Report([]), [])
    with pytest.raises(KeyError):
        await store.save(draft, {})
    with pytest.raises(KeyError):
        await store.load("../x")
    assert not (tmp_path / "x").exists()


async def test_store_round_trip_and_no_temp_file(tmp_path):
    store = FolderDraftStore(tmp_path)
    id_ = await submitted(store)
    draft = await store.load(id_)
    await Review(store).decide(id_, State.ACCEPTED, "bob", "fine")
    again = await store.load(id_)
    assert again.to_dict()["contributor"] == draft.to_dict()["contributor"]
    assert again.report.to_dict() == draft.report.to_dict()
    assert again.history[0].comment == "fine"
    assert Draft.from_dict(again.to_dict()) == again
    assert sorted(p.name for p in (tmp_path / id_).iterdir()) == [
        "draft.json",
        "files",
    ]
