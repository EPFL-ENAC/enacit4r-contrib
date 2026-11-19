# enacit4r-contrib

A Python library for data contributions in EPFL ENAC IT4R projects. A
contributor uploads files in the browser. The library checks them with the
project's own rules and sends them for review. With the first sink, the review
is a GitHub pull request.

The same four steps appear in every project
([comparison](docs/research/contribution-pipelines.md)):

1. Intake: `read_upload` takes loose files, a `.zip` or a `.tar.gz`. It
   refuses unsafe paths and oversized uploads, and lists files that the
   template does not expect.
2. Validation: your project gives a `Validator`. It returns a list of `Issue`
   (message, file, row, column, value, severity).
3. Sink: a `Sink` stores the contribution for review. `GitHubPRSink` commits it
   to `submissions/<id>/` on a new branch and opens a pull request.
4. Decision: a person reviews and merges. This step stays in your project.

## Install

The library is a git dependency, pinned by tag, like `enacit4r-files`:

```toml
[project]
dependencies = ["enacit4r-contrib[github]"]

[tool.uv.sources]
enacit4r-contrib = { git = "https://github.com/EPFL-ENAC/enacit4r-contrib", tag = "0.1.0" }
```

A Docker build that installs a git dependency needs `git` in the build stage.

## Use it in a FastAPI backend

```python
from enacit4r_contrib import Issue, Pipeline, contribution_router
from enacit4r_contrib.github import GitHubRepo
from enacit4r_contrib.sinks import GitHubPRSink

ALLOW = ["data.csv", "curves/*.csv"]


async def validate(bundle: dict[str, bytes]) -> list[Issue]:
    if "data.csv" not in bundle:
        return [Issue("data.csv is missing")]
    return []


repo = GitHubRepo(
    "EPFL-ENAC/my-dataset", app_id=..., private_key=..., installation_id=...
)
sink = GitHubPRSink(repo, base="dev", reviewers=["curator-login"])
app.include_router(contribution_router(Pipeline(validate, sink), allow=ALLOW))
```

The router adds two endpoints. Both take `multipart/form-data`, with one part
per file in the field `files`. The file name of a part is its relative path.

| Endpoint | Answers |
| --- | --- |
| `POST /validate` | 200 `{valid, issues}`. 400 `{detail}` for a refused upload. |
| `POST /contributions` | Also takes `name`, `email`, `institution`, `orcid`, `note`. 201 `{valid, issues, id, url}`. 422 when the data or the contributor fields are not valid. 429 when the client sends too many, or when too many contributions wait for review. 502 when GitHub refuses. 503 when contributions are switched off (`enabled=False`). |

The rate limit is kept in the process. If you run several replicas, each
replica counts on its own.

## GitHub credentials

`GitHubRepo` takes a GitHub App installation (`app_id`, `private_key`,
`installation_id`) or a `token`. It needs these permissions on the
repository: contents (write) and pull requests (write).

## Tests in your project

`enacit4r_contrib.testing.FakeRepo` keeps the branches, commits and pull
requests in memory. Give it to `GitHubPRSink` in place of `GitHubRepo`.

## Other kinds of sink

A project that keeps drafts in S3 or in a database implements `Sink`:

- `submit(bundle, contributor, report)` stores the draft and returns a
  `Receipt(id, url)`.
- `open_count()` returns the number of drafts that wait for a review.

The review states and the publication step stay in that project.

## Develop

```bash
make test    # pytest
make lint    # ruff
```
