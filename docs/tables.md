# Merge rows into a table

Some data repositories keep one main CSV table for each data type. By
default, the sink writes each contribution to a `submissions/<id>/` folder.
With a table merge, the sink adds the new rows to the main table in the pull
request. Reviewers then see a row diff of the real table.

## Set up the sink

Give a `TableMerge` to `GitHubPRSink`:

```python
from enacit4r_contrib import TableMerge
from enacit4r_contrib.sinks import GitHubPRSink

sink = GitHubPRSink(
    repo,
    base="main",
    table=TableMerge("data/materials.csv", id_column="id", fill="NA"),
)
```

The sink commits the bundle files at their own paths. The bundle must hold
the file at `TableMerge.path`. The sink reads that table from the base branch
and merges the new rows into it.

## How the merge works

- The table keeps its header and its column order.
- The sink matches each new column to a table column by name.
- A missing or blank cell gets the `fill` value.
- A column in `fixed` gets the fixed value for each new row.
- A cell that starts like a formula, such as `=SUM(A1)`, gets a leading `'`.
- The table keeps its line endings.

The merge stops with a `TableError` when a new column is not in the table, or
when the id column is missing or empty. It stops with `DuplicateIds` when an
id is already in the table or appears twice in the new rows. The sink raises
these errors before it creates a branch.

## Find duplicate ids before submit

Call `table_ids` on the current table to get the known ids. Then call
`duplicate_id_issues` in your validator. Each duplicate becomes an error
`Issue` with its line number, so the contributor sees the problem before
the submit step.

## Next step

Read [Sinks](sinks.md) to see the other sink options.
