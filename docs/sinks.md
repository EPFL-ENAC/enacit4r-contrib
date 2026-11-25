# Sinks

A sink stores a valid contribution so that a person can review it. The
library gives two sinks. `GitHubPRSink` opens a pull request.
`DraftSink` saves a draft in storage. This page tells you what
`GitHubPRSink` writes.

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

After the merge, the [ingest action](ingest.md) folds the submission into your data.

## Add trailers to the commit message

`enacit4r_contrib.trailers.build_commit_message` writes the standard
trailers. To add your own trailers, give them in `extra`. The function
writes them after the standard trailers.

```python
from enacit4r_contrib.trailers import build_commit_message

message = build_commit_message(
    "Data contribution", contributor, extra=[("Dataset", "walls")]
)
```

`format_trailers(title, pairs)` writes a title, a blank line and one
`Key: value` line for each pair. It makes each value one line. It
removes each pair that has an empty value. `address(name, email)` gives
`Name <email>`, and `split_address` gives the name and the email back.

## Write a different sink

A `Sink` is a class with two async methods. You do not need to
inherit from a base class.

- `submit(bundle, contributor, report)` stores the contribution and
  returns a `Receipt(id, url)`.
- `open_count()` returns the number of contributions that wait for a
  review.

For the draft-in-storage pattern, use `DraftSink`. It saves each
contribution as a draft in a folder, in S3, or in a database. Read
[Drafts in storage](drafts.md).

## Next step

Read [Testing](testing.md) to test your sink and your routes without
GitHub.

To merge rows into one main table, read [Merge rows into a table](tables.md).
