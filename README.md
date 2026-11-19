# enacit4r-contrib

A Python library for data contributions in EPFL ENAC IT4R projects. A
contributor uploads files in the browser. The library checks them with
the rules of your project and sends them for review, for example as a
GitHub pull request.

The documentation is at
[epfl-enac.github.io/enacit4r-contrib](https://epfl-enac.github.io/enacit4r-contrib/).

## Install

The library is a git dependency, pinned by tag:

```toml
[project]
dependencies = ["enacit4r-contrib[github]"]

[tool.uv.sources]
enacit4r-contrib = { git = "https://github.com/EPFL-ENAC/enacit4r-contrib", tag = "0.3.0" }
```

## Use it in a FastAPI backend

```python
from enacit4r_contrib import Bundle, Issue, Pipeline, contribution_router
from enacit4r_contrib.github import GitHubRepo
from enacit4r_contrib.sinks import GitHubPRSink


async def validate(bundle: Bundle) -> list[Issue]:
    if "data.csv" not in bundle:
        return [Issue("data.csv is missing", file="data.csv")]
    return []


repo = GitHubRepo(
    "EPFL-ENAC/my-dataset", app_id=..., private_key=..., installation_id=...
)
sink = GitHubPRSink(repo, base="main", reviewers=["curator-login"])
app.include_router(contribution_router(Pipeline(validate, sink), allow=["*.csv"]))
```

The router adds `POST /validate` and `POST /contributions`. The site
tells you how to write a validator, create the GitHub App, call the
endpoints from the browser, and test your integration.

After a merge, the `ingest` GitHub action folds the submission into your data. See [Ingest](https://epfl-enac.github.io/enacit4r-contrib/ingest/).

To keep contributions as drafts for an admin page instead of pull requests, see [Drafts in storage](https://epfl-enac.github.io/enacit4r-contrib/drafts/).

## Develop

```bash
make test        # pytest
make lint        # ruff
make docs        # serve the documentation site
make docs-build  # build the site in strict mode
```

To start, read
[Getting started](https://epfl-enac.github.io/enacit4r-contrib/getting-started/).
