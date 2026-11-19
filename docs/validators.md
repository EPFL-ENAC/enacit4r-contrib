# Validators

A validator holds the rules of your project. The library does not know
what valid data is for your dataset, so it calls your validator. This
page gives the contract, the problem format, and the path rules that
apply before your validator runs.

## The contract

A `Validator` is an async function. It takes a `Bundle` and returns a
list of `Issue`. A `Bundle` is a `dict[str, bytes]`: the relative path
of each file, and its content.

```python
from enacit4r_contrib import Bundle, Issue


async def validate(bundle: Bundle) -> list[Issue]:
    return []
```

An empty list means that the contribution is clean. The router calls
the validator for each request to `POST /validate` and to
`POST /contributions`. If the validator raises an exception,
`POST /validate` answers 503 and `POST /contributions` answers 502.
Thus, return an `Issue` for bad data. Do not raise.

## The Issue fields

An `Issue` is one problem. Every stage uses this format: the intake,
your validator, and the browser.

| Field      | Type                       | Meaning                                       |
| ---------- | -------------------------- | --------------------------------------------- |
| `message`  | `str`                      | The text for the contributor                  |
| `file`     | `str` or `None`            | The path in the bundle                        |
| `row`      | `int` or `None`            | The line in the file, from 1, header included |
| `column`   | `str` or `None`            | The column name                               |
| `value`    | `str` or `None`            | The value that is not correct                 |
| `severity` | `"error"` or `"warning"`   | The default is `"error"`                      |

An error blocks the submission. A warning informs the contributor and
the reviewer, but the submission continues. `GitHubPRSink` copies each
warning into the pull request body.

## Allow and skip globs

Before your validator runs, the intake compares each path with two
lists of glob patterns. You give the two lists to
`contribution_router`.

- `allow`: the paths that your template contains. A path that matches
  goes into the bundle.
- `skip`: the paths that you drop. A path that matches gives a warning
  and does not go into the bundle.
- Any other path gives an error: "Unexpected file".

The patterns use `fnmatch`. In `fnmatch`, `*` also matches `/`. Thus
`curves/*.csv` matches `curves/a/b.csv`.

## The top-folder strip

A contributor often uploads one folder, for example `my-walls/`. If all
the paths start with the same top folder, the intake removes it. Thus
`my-walls/data.csv` becomes `data.csv`. Write your `allow` globs
without the top folder.

The intake also drops system files, for example `.DS_Store` and
`__MACOSX/`. It refuses absolute paths and paths that contain `..`.

## An example

The eesd-modern-masonry-walls-db project has a full validator in
[contribution.py](https://github.com/EPFL-ENAC/eesd-modern-masonry-walls-db/blob/dev/backend/modernmasonrydatabase/contribution.py).
It compares the submission with the published dataset. This short
example uses the same structure:

```python
import csv
import io

from enacit4r_contrib import Bundle, Issue

DATABASE_CSV = "database.csv"
ALLOW = [DATABASE_CSV, "README.txt", "02_fd_curve/*.csv"]
SKIP = ["07_fig_setup/*"]
CURVE_HEADER = ["drift [%]", "horizontal_force [kN]"]


async def validate(bundle: Bundle) -> list[Issue]:
    if DATABASE_CSV not in bundle:
        return [Issue(f"{DATABASE_CSV} is missing", file=DATABASE_CSV)]
    issues: list[Issue] = []
    for path, data in sorted(bundle.items()):
        if not path.startswith("02_fd_curve/"):
            continue
        rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig", "replace"))))
        if not rows or rows[0] != CURVE_HEADER:
            issues.append(Issue("wrong header", file=path, row=1))
        elif len(rows) < 3:
            issues.append(Issue("needs 2 data rows", file=path, severity="warning"))
    return issues
```

Give `ALLOW` and `SKIP` to the router:

```python
contribution_router(Pipeline(validate, sink), allow=ALLOW, skip=SKIP)
```

If your rules need a reference file, load it in the validator. The
eesd project downloads its dataset and keeps it in a cache for ten
minutes.

## Next step

Read [HTTP API](http-api.md) to see how the browser receives the
issues.
