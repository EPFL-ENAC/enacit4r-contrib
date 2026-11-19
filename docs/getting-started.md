# Getting started

This page tells you how to add enacit4r-contrib to a FastAPI backend.
At the end, your backend has two endpoints: one checks an upload, and
one submits it as a GitHub pull request. If you already have the GitHub
App, the work takes approximately 15 minutes.

## Install the library

The library is a git dependency. Pin it to a tag, so that a new
release does not change your backend without a review. The tag has no
`v` prefix. The `github` extra installs the GitHub client.

```toml
[project]
dependencies = ["enacit4r-contrib[github]"]

[tool.uv.sources]
enacit4r-contrib = { git = "https://github.com/EPFL-ENAC/enacit4r-contrib", tag = "0.4.0" }
```

Then update the lock file:

```bash
uv lock
```

> Note: uv clones the repository to install a git dependency. If you
> build a Docker image, install `git` in the build stage.

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends git
```

## Add the endpoints

The function `contribution_router` returns a FastAPI router with the
two endpoints. It takes a `Pipeline`, which joins your validator and a
sink. The `allow` argument lists the paths that an upload can contain.

```python
import os

from fastapi import FastAPI

from enacit4r_contrib import Bundle, Issue, Pipeline, contribution_router
from enacit4r_contrib.github import GitHubRepo
from enacit4r_contrib.sinks import GitHubPRSink

ALLOW = ["data.csv", "curves/*.csv"]


async def validate(bundle: Bundle) -> list[Issue]:
    if "data.csv" not in bundle:
        return [Issue("data.csv is missing", file="data.csv")]
    return []


repo = GitHubRepo(
    "EPFL-ENAC/my-dataset",
    app_id=os.environ["GITHUB_APP_ID"],
    private_key=os.environ["GITHUB_APP_PRIVATE_KEY"],
    installation_id=int(os.environ["GITHUB_APP_INSTALLATION_ID"]),
)
sink = GitHubPRSink(repo, base="main", reviewers=["curator-login"])
pipeline = Pipeline(validate, sink, max_open=25)

app = FastAPI()
app.include_router(contribution_router(pipeline, allow=ALLOW), prefix="/api")
```

The [GitHub App](github-app.md) page tells you how to get the three
settings. The [Validators](validators.md) page tells you how to write
real rules.

## Switch contributions off

If the GitHub settings are not available, you can keep the check
endpoint and stop the submissions. Give `enabled=False` to the router.
Then `POST /contributions` answers 503, and `POST /validate` continues
to work.

```python
app.include_router(
    contribution_router(pipeline, allow=ALLOW, enabled=False), prefix="/api"
)
```

With `enabled=False`, the router does not call the sink. Thus the sink
does not need a working repository, for example in a local development
environment.

## Next step

Write the rules of your project. Read [Validators](validators.md).
