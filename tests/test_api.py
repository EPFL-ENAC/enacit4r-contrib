import json

import httpx
import pytest
from fastapi import FastAPI

from enacit4r_contrib import Issue, Pipeline, contribution_router
from enacit4r_contrib.sinks import GitHubPRSink
from enacit4r_contrib.testing import FakeRepo

PERSON = {"name": "Ada", "email": "ada@example.org", "institution": "EPFL"}


async def validate(bundle):
    issues = []
    if "bad.csv" in bundle:
        issues.append(Issue("bad data", file="bad.csv"))
    if "warn.csv" in bundle:
        issues.append(Issue("odd data", file="warn.csv", severity="warning"))
    return issues


def files(*names):
    return [("files", (n, b"a,b\n1,2\n", "text/csv")) for n in names]


def make(repo=None, max_open=25, **kw):
    repo = repo or FakeRepo()
    pipeline = Pipeline(validate, GitHubPRSink(repo, base="main"), max_open=max_open)
    app = FastAPI()
    app.include_router(contribution_router(pipeline, allow=["*.csv"], **kw))
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://t")
    return client, repo


async def test_validate_valid_with_warning():
    client, _ = make()
    r = await client.post("/validate", files=files("good.csv", "warn.csv"))
    assert r.status_code == 200
    assert r.json()["valid"] is True
    assert [i["severity"] for i in r.json()["issues"]] == ["warning"]


async def test_validate_invalid():
    client, _ = make()
    r = await client.post("/validate", files=files("good.csv", "bad.csv"))
    assert r.status_code == 200 and r.json()["valid"] is False
    assert r.json()["issues"][0]["file"] == "bad.csv"


async def test_validate_unexpected_path_is_an_issue_and_validator_still_runs():
    client, _ = make()
    r = await client.post("/validate", files=files("bad.csv", "notes.txt"))
    messages = [i["message"] for i in r.json()["issues"]]
    assert r.status_code == 200 and r.json()["valid"] is False
    assert any(m.startswith("Unexpected file") for m in messages)
    assert "bad data" in messages


async def test_validate_hostile_path_is_400():
    client, _ = make()
    r = await client.post("/validate", files=files("../x.csv"))
    assert r.status_code == 400 and "Unsafe path" in r.json()["detail"]


async def test_file_over_cap_is_400():
    client, _ = make(max_file_bytes=4)
    r = await client.post("/validate", files=files("good.csv"))
    assert r.status_code == 400 and "too large" in r.json()["detail"]


async def test_contribution_success_opens_a_pr():
    client, repo = make()
    r = await client.post(
        "/contributions", data=PERSON, files=files("good.csv", "warn.csv")
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["valid"] is True and body["url"] == repo.pulls[0]["url"]
    assert set(repo.commits[0]["files"]) == {
        f"submissions/{body['id']}/good.csv",
        f"submissions/{body['id']}/warn.csv",
    }


async def test_invalid_contribution_is_422_and_opens_no_pr():
    client, repo = make()
    r = await client.post("/contributions", data=PERSON, files=files("bad.csv"))
    assert r.status_code == 422 and r.json()["valid"] is False
    assert repo.pulls == []


async def test_intake_error_is_422_and_opens_no_pr():
    client, repo = make()
    r = await client.post(
        "/contributions", data=PERSON, files=files("good.csv", "notes.txt")
    )
    assert r.status_code == 422 and r.json()["valid"] is False
    assert repo.pulls == []


async def test_missing_name_is_422():
    client, repo = make()
    data = {k: v for k, v in PERSON.items() if k != "name"}
    r = await client.post("/contributions", data=data, files=files("good.csv"))
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"] == ["name"]
    assert repo.pulls == []


async def test_blank_optional_fields_are_ignored():
    client, _ = make()
    data = {**PERSON, "orcid": "", "note": ""}
    r = await client.post("/contributions", data=data, files=files("good.csv"))
    assert r.status_code == 201, r.text


async def test_disabled_is_503_and_validate_still_works():
    client, _ = make(enabled=False)
    r = await client.post("/contributions", data=PERSON, files=files("good.csv"))
    assert r.status_code == 503
    assert r.json() == {"detail": "Contributions are not open yet"}
    r = await client.post("/validate", files=files("good.csv"))
    assert r.status_code == 200


async def test_rate_limit():
    client, repo = make(rate_limit=(2, 3600))
    codes = [
        (
            await client.post("/contributions", data=PERSON, files=files("good.csv"))
        ).status_code
        for _ in range(3)
    ]
    assert codes == [201, 201, 429]
    assert len(repo.pulls) == 2


async def test_queue_full_is_429():
    repo = FakeRepo(pulls=[{"branch": "contrib/old", "open": True}])
    client, _ = make(repo, max_open=1)
    r = await client.post("/contributions", data=PERSON, files=files("good.csv"))
    assert r.status_code == 429 and "wait for review" in r.json()["detail"]


async def test_sink_failure_is_502():
    client, _ = make(FakeRepo(fail_on="open_pull"))
    r = await client.post("/contributions", data=PERSON, files=files("good.csv"))
    assert r.status_code == 502
    assert r.json()["detail"].startswith("Could not open the review request")


@pytest.mark.parametrize(
    "first,second,expected",
    [("1.1.1.1, 2.2.2.2", "9.9.9.9, 2.2.2.2", 429), ("1.1.1.1", "2.2.2.2", 201)],
)
async def test_rate_limit_keys_on_last_forwarded_for(first, second, expected):
    client, _ = make(rate_limit=(1, 3600))
    post = client.post
    r1 = await post(
        "/contributions",
        data=PERSON,
        files=files("good.csv"),
        headers={"X-Forwarded-For": first},
    )
    r2 = await post(
        "/contributions",
        data=PERSON,
        files=files("good.csv"),
        headers={"X-Forwarded-For": second},
    )
    assert (r1.status_code, r2.status_code) == (201, expected)


async def test_nested_paths_keep_their_folders():
    client, repo = make()
    r = await client.post(
        "/contributions", data=PERSON, files=files("walls/01/a.csv", "walls/02/b.csv")
    )
    assert r.status_code == 201, r.text
    assert set(repo.commits[0]["files"]) == {
        f"submissions/{r.json()['id']}/01/a.csv",
        f"submissions/{r.json()['id']}/02/b.csv",
    }


async def test_validate_answers_503_when_the_validator_fails():
    async def broken(bundle):
        raise RuntimeError("dataset unreachable")

    app = FastAPI()
    pipeline = Pipeline(broken, GitHubPRSink(FakeRepo(), base="main"))
    app.include_router(contribution_router(pipeline, allow=["*.csv"]))
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://t")
    r = await client.post("/validate", files=files("good.csv"))
    assert r.status_code == 503
    assert "cannot be checked" in r.json()["detail"]


async def test_skipped_files_show_in_the_answer_and_the_pr():
    repo = FakeRepo()
    pipeline = Pipeline(validate, GitHubPRSink(repo, base="main"))
    app = FastAPI()
    app.include_router(contribution_router(pipeline, allow=["*.csv"], skip=["*.jpg"]))
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://t")
    up = files("good.csv") + [("files", ("photo.jpg", b"\xff\xd8", "image/jpeg"))]
    r = await client.post("/contributions", files=up, data=PERSON)
    assert r.status_code == 201
    assert [i["file"] for i in r.json()["issues"]] == ["photo.jpg"]
    assert "photo.jpg" in repo.pulls[0]["body"]
    assert list(repo.commits[0]["files"]) == [f"submissions/{r.json()['id']}/good.csv"]


async def test_contributor_json_field_is_accepted():
    client, repo = make()
    data = {"contributor": json.dumps(PERSON), "name": "ignored"}
    r = await client.post("/contributions", data=data, files=files("good.csv"))
    assert r.status_code == 201, r.text


async def test_contributor_invalid_json_is_422():
    client, _ = make()
    r = await client.post(
        "/contributions", data={"contributor": "{not json"}, files=files("good.csv")
    )
    assert r.status_code == 422


async def test_contributor_json_is_validated():
    client, _ = make()
    bad = json.dumps({**PERSON, "email": "nope"})
    r = await client.post(
        "/contributions", data={"contributor": bad}, files=files("good.csv")
    )
    assert r.status_code == 422


async def test_ignore_case_in_router():
    up = [("files", ("X.CSV", b"a,b\n1,2\n", "text/csv"))]
    client, _ = make()
    r = await client.post("/validate", files=up)
    assert r.json()["valid"] is False
    client, _ = make(ignore_case=True)
    r = await client.post("/validate", files=up)
    assert r.json()["valid"] is True


async def test_no_state_route_without_public_state():
    client, _ = make()
    r = await client.get("/contributions/x/state")
    assert r.status_code in (404, 405)
