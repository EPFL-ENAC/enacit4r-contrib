# Sinks

A sink stores a valid contribution so that a person can review it. The
library gives one sink, `GitHubPRSink`, for the pull request pattern.
This page tells you what that sink writes, and how to write a sink for
the draft-in-storage pattern.

## What GitHubPRSink writes

For each contribution, `GitHubPRSink` makes one branch, one commit, and
one pull request.

| Item              | Value                                                      |
| ----------------- | ---------------------------------------------------------- |
| ID                | `<date>-<name slug>-<6 hex characters>`                    |
| Folder            | `submissions/<id>/`, with the paths of the bundle under it |
| Branch            | `contrib/<id>`, made from the head of `base`               |
| Commit message    | `Data contribution from <name>`, with the trailers         |
| Pull request title | `Data contribution: <name> (<institution>)`               |
| Pull request body | The contributor, the file list, and the warnings           |

An example ID is `2026-11-19-ada-lovelace-3f9a1c`. The sink returns a
`Receipt` with the ID and the URL of the pull request.

```python
sink = GitHubPRSink(
    repo,
    base="dev",
    folder="submissions",
    branch_prefix="contrib/",
    reviewers=["curator-login"],
    title="Data contribution",
)
```

Each argument after `base` has the default value that this example
shows, except `reviewers`. The pull request body changes each `@` at the
start of a word, so that GitHub does not notify other users.

## Reviewers and failures

After it opens the pull request, the sink asks the `reviewers` to
review it. If this request fails, the sink writes a log entry and the
contribution continues. Make sure that each reviewer has access to the
data repository.

If the commit or the pull request fails, the sink deletes the branch.
Then it raises the error again, and the router answers 502. Thus a
failure does not leave a branch without a pull request.

`open_count` counts the open pull requests with a branch that starts
with `branch_prefix`. The pipeline compares this number with
`max_open`.

## Write a different sink

A `Sink` is a class with two async methods. You do not need to
inherit from a base class.

- `submit(bundle, contributor, report)` stores the contribution and
  returns a `Receipt(id, url)`.
- `open_count()` returns the number of contributions that wait for a
  review.

This example writes each contribution to a folder on the server:

```python
import json
import secrets
from pathlib import Path

from enacit4r_contrib import Bundle, Contributor, Receipt, Report


class FolderSink:
    def __init__(self, root: Path):
        self.root = root

    async def submit(
        self, bundle: Bundle, contributor: Contributor, report: Report
    ) -> Receipt:
        id_ = secrets.token_hex(8)
        folder = self.root / "pending" / id_
        for path, data in bundle.items():
            (folder / path).parent.mkdir(parents=True, exist_ok=True)
            (folder / path).write_bytes(data)
        info = {"contributor": contributor.model_dump(), "report": report.to_dict()}
        (folder / "info.json").write_text(json.dumps(info))
        return Receipt(id_, f"/admin/contributions/{id_}")

    async def open_count(self) -> int:
        pending = self.root / "pending"
        return sum(1 for p in pending.iterdir()) if pending.exists() else 0
```

The same structure works for other storage:

- An S3 draft: write the files under `draft/<id>/` with
  `enacit4r_files`. Count the drafts in `open_count`.
- A database row: insert one row with the state `in-review`. Count the
  rows in that state.

The review states and the publication stay in your project. Your admin
action moves the draft out of `pending`, so that `open_count` goes down.

## Next step

Read [Testing](testing.md) to test your sink and your routes without
GitHub.
