# Testing

Your tests must not open real pull requests on GitHub. The library
gives `FakeRepo`, a repository in memory. Give it to `GitHubPRSink` in
place of `GitHubRepo`. Then your tests run the real router, your real
validator, and the real sink, without network access.

## What FakeRepo records

`FakeRepo` has the same methods as `GitHubRepo`. Each method records
what it did in a public attribute:

| Attribute   | Content                                                   |
| ----------- | --------------------------------------------------------- |
| `files`     | The default branch, as `path: bytes`. You can fill it.    |
| `branches`  | Each branch that a commit made                            |
| `commits`   | Each commit, with `branch`, `base`, `message`, `files`    |
| `pulls`     | Each pull request, with `title`, `body`, `url`, `open`    |
| `reviewers` | The reviewers for each pull request number                |
| `deleted`   | The branches that the sink deleted                        |
| `heads`     | The last commit sha of each branch                        |

`FakeRepo` also fakes the methods that edit an open contribution.
`commit_on_branch` changes `branches`, adds to `commits` and moves
`heads`. It raises `BranchMoved` when `head` is not `heads[branch]`.
`update_pull_body` changes the body in `pulls`. `pull_files` gives
the files of the branch that are not the same as in the base branch.

To test a failure, set `fail_on` to the name of a method, for example
`fail_on="open_pull"`. That method then raises `RuntimeError`.

## A pytest example

This test sends a request to the router through
`httpx.ASGITransport`. The transport calls the FastAPI app directly,
without a server. Install `pytest`, `pytest-asyncio`, and `httpx` in
your dev dependencies, and set `asyncio_mode = "auto"` for pytest.

```python
import httpx
from fastapi import FastAPI

from enacit4r_contrib import Pipeline, contribution_router
from enacit4r_contrib.sinks import GitHubPRSink
from enacit4r_contrib.testing import FakeRepo

from myproject.contribution import ALLOW, validate

PERSON = {"name": "Ada", "email": "ada@example.org", "institution": "EPFL"}


def make_client(repo: FakeRepo) -> httpx.AsyncClient:
    pipeline = Pipeline(validate, GitHubPRSink(repo, base="main"))
    app = FastAPI()
    app.include_router(contribution_router(pipeline, allow=ALLOW))
    transport = httpx.ASGITransport(app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_a_valid_contribution_opens_a_pull_request():
    repo = FakeRepo()
    client = make_client(repo)
    files = [("files", ("data.csv", b"a,b\n1,2\n", "text/csv"))]

    r = await client.post("/contributions", files=files, data=PERSON)

    assert r.status_code == 201
    assert repo.pulls[0]["title"] == "Data contribution: Ada (EPFL)"
    assert f"submissions/{r.json()['id']}/data.csv" in repo.commits[0]["files"]


async def test_a_failed_pull_request_deletes_the_branch():
    repo = FakeRepo(fail_on="open_pull")
    client = make_client(repo)
    files = [("files", ("data.csv", b"a,b\n1,2\n", "text/csv"))]

    r = await client.post("/contributions", files=files, data=PERSON)

    assert r.status_code == 502
    assert repo.deleted and not repo.branches
```

Replace `myproject.contribution` with the module of your validator.
The tests of the library in
[tests/test_api.py](https://github.com/EPFL-ENAC/enacit4r-contrib/blob/main/tests/test_api.py)
show more cases.

## Test the validator alone

A validator is an async function. Thus you can test it without the
router. Give it a `Bundle` and compare the issues.

```python
async def test_a_missing_database_is_an_error():
    issues = await validate({"README.txt": b"hello"})
    assert [i.severity for i in issues] == ["error"]
```

## Next step

Add a test for each rule of your validator. Then read
[Contribution pipelines in five projects](research/contribution-pipelines.md)
for the design background.
