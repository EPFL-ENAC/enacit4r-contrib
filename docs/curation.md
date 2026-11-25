# Read open contributions

A curator reviews the open contributions before a merge. This page tells
you how to read them for a curation page. Each contribution is an open
pull request that `GitHubPRSink` made.

## Get the list

Call `open_contributions` with a `GitHubRepo`. The function reads the
open pull requests, newest first. It keeps each pull request with a head
branch that starts with `branch_prefix`. Then it reads the commits of
each pull request and parses the trailers.

```python
from enacit4r_contrib import open_contributions
from enacit4r_contrib.github import GitHubRepo

repo = GitHubRepo("owner/name", token=token)
for c in await open_contributions(repo, base="dev"):
    print(c.pull.number, c.pull.title, c.submitter_name, c.submitter_email)
```

Each item is a `Contribution`. It has these fields.

| Field             | Value                                                   |
| ----------------- | ------------------------------------------------------- |
| `pull`            | A `PullInfo` with the number, URL, title, body and dates |
| `trailers`        | The trailers of the first commit with `Submitted-by`    |
| `submitter_name`  | The name in the first `Submitted-by` value              |
| `submitter_email` | The email in the first `Submitted-by` value             |

If no commit has a `Submitted-by` trailer, `trailers` is empty. Then the
name and the email are empty strings.

Set `branch_prefix=""` to get all open pull requests. Set `limit` to read
more or fewer pull requests. The default is 100.

## Read more about one pull request

`GitHubRepo` gives more read methods.

- `get_pull(number)` gives one `PullInfo`.
- `pull_commits(number)` gives the commits as `CommitInfo` items.
- `pull_comments(number)` gives the comments as `CommentInfo` items.
- `list_dir(path, ref=None)` gives the file names in a folder.

`FakeRepo` has the same methods. Use it to test your curation page
without GitHub. Put comments in `FakeRepo.comments`.

## Next step

To test your page with `FakeRepo`, read [Testing](testing.md).
