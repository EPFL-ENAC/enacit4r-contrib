# Withdraw data

Sometimes data that you accepted must leave the dataset. Examples are
test data, an error, or a request from the author. The `withdraw`
action and the helpers of `enacit4r_contrib.ingest` do this removal
with the same safety as the ingest.

## The number policy

A withdrawn record keeps its number. By default, the number is
retired: your command replaces the row with a placeholder row that
holds only the number. The next ingest does not give this number to
new data, because `next_number` reads the placeholder.

A number that reached production can be in a citation. If you give it
to different data, the citation points to the wrong data. If the data
never reached production, you can delete the row and reuse the number.

## Pattern B: the withdraw action

A curator starts the action by hand. The action runs on the base branch.

1. It runs your command from the repository root, with `TARGET` in
   the environment. `TARGET` is the text of the input `target`, for
   example a record number.
2. If the command changes nothing, the action fails with
   `nothing to withdraw for <target>`.
3. It makes one commit: `chore(data): withdraw <target>` (input
   `commit-prefix`). The input `reason` goes into the commit body.
4. It pushes to the base branch. If the base branch moved, the action
   fetches it, resets to it, and runs the command again. After 3
   refused pushes, the action fails.
5. If you set `deploy-workflow`, it starts that workflow on the base
   branch.

The inputs `token`, `deploy-workflow`, `git-user-name` and
`git-user-email` have the same defaults as in [Ingest](ingest.md).

### Add the workflow

The `concurrency` group is the same as the group of the ingest
workflow. Thus an ingest and a withdrawal never run at the same time
on one branch.

```yaml
name: Withdraw

on:
  workflow_dispatch:
    inputs:
      target:
        description: Record number to withdraw
        required: true
      reason:
        description: Why the data leaves
        required: true

permissions:
  contents: write
  actions: write

concurrency:
  group: ingest-${{ github.ref_name }}
  cancel-in-progress: false

jobs:
  withdraw:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: astral-sh/setup-uv@v6
      - uses: EPFL-ENAC/enacit4r-contrib/withdraw@0.5.0
        with:
          target: ${{ inputs.target }}
          reason: ${{ inputs.reason }}
          base: ${{ github.ref_name }}
          command: uv run python scripts/withdraw.py "$TARGET"
          deploy-workflow: deploy.yml
```

The ingest workflow uses the group
`ingest-${{ github.event.pull_request.base.ref }}`. Start the withdraw
workflow on the same branch, so that the two names are the same.

### Write the command

The command uses two methods of `Plan`:

- `Plan.rewrite_rows(path, change)` calls `change` for each data row.
  `change` returns the row to keep it, a new row to replace it, or
  `None` to delete it. The bytes of the other rows do not change. The
  parameter `header_rows` (default 1) gives the number of header rows.
  If no row changes, the check fails. To allow this, set
  `expect_match=False`.
- `Plan.delete(path)` deletes a file. The file must exist.

The plan checks all the changes before the first write. If one change
cannot be done, the plan writes nothing and raises `IngestError`.

This example retires record `id` in `data/table.csv` and deletes its
curve `data/curves/<id>.csv`.

```python
import sys
from pathlib import Path

from enacit4r_contrib.ingest import Plan, run

DATA = Path("data")


def withdraw(target: Path) -> list[str]:
    number = str(target)
    plan = Plan()
    plan.rewrite_rows(
        DATA / "table.csv",
        lambda row: [number] + [""] * (len(row) - 1) if row[0] == number else row,
    )
    plan.delete(DATA / "curves" / f"{number}.csv")
    plan.apply()
    return [f"withdrew {number}, the number stays retired"]


if __name__ == "__main__":
    sys.exit(run(withdraw))
```

`run` gives its argument as a `Path`. If the record does not exist,
the plan raises `IngestError`, `run` prints the problems, and the
action pushes nothing.

## Pattern A: the withdrawn state

For drafts, `Review` can move a draft from `published` to `withdrawn`.
A withdrawal must have a comment.

```python
async def on_withdraw(draft):
    await retire_in_database(draft.id)  # your project's code


review = Review(store, on_publish=on_publish, on_withdraw=on_withdraw)
```

`Review` calls `on_withdraw(draft)` before it saves the new state. If
the hook fails, the draft stays `published` and `Review` raises the
error again. Then `review_router` answers 502, and the admin can try
again.

## Next step

Read [Drafts in storage](drafts.md) for the other states of a draft.
