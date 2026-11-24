# Adopt the draft pattern

This page tells you how to move a project from its own upload and
review code to `enacit4r_contrib.drafts`. hobel-iaqdb, ALICE-ETHZ-AREMA
and eesd-mmsdb each wrote this code. The library now does the same
work, with tests and one error format.

## What you get

- `contribution_router`: `/validate` and `/contributions`, safe intake
  of files and archives, your validator, and a rate limit.
- `DraftSink` and a `DraftStore`: each valid upload becomes a draft in
  `submitted`. The library gives `FolderDraftStore`.
- `Review`: the moves between states, a log of each decision, and the
  hooks `on_publish`, `on_withdraw` and `on_change`.
- `review_router`: the admin endpoints. Your project gives the login.
- Your own contributor model, a JSON `contributor` field, the upload
  hook `on_submit`, a public state route, `secret_id` and `ignore_case`.
- Your own text for a refused file (`unexpected`), for example "Not a 3D
  model". The default text speaks of a template.

## Procedure

1. Make an inventory of your current upload: the form fields, the
   allowed files, the storage, the e-mails, the admin actions and the
   publication.
2. Find the misfits. Compare the inventory with
   [Drafts in storage](drafts.md). If your project needs a feature that
   the library does not have, add it to the library first.
3. Write the validator. Move your current checks into one function
   that returns `Issue` items. Read [Validators](validators.md).
4. Choose the store. Use `FolderDraftStore` for files on a volume.
   For S3 or database rows, write a class with the four methods of
   `DraftStore`.
5. Write the hooks. `on_publish` runs the code of your current
   publish action. `on_withdraw` is its reverse. Read
   [Withdraw data](withdraw.md).
6. Write the reviewer dependency from your current auth. It returns
   the name of the reviewer, or raises 401 or 403.
7. Mount the two routers next to the old routes. Point the frontend at
   the new routes. Keep the old routes until step 8 is done.
8. Migrate or close the drafts that wait in the old storage.
9. Delete the old routes and their code. Make sure that no old route
   stays open without a login.

## Wiring skeleton

Replace `validate`, `Person`, the hooks and `reviewer` with your code.

```python
store = FolderDraftStore(Path("/data/drafts"), contributor=Person)
sink = DraftSink(store, make_id=secret_id, on_submit=mail_admins)
review = Review(store, on_publish=publish, on_withdraw=unpublish)

app.include_router(
    contribution_router(
        Pipeline(validate, sink),
        allow=["*.csv"],
        contributor=Person,
        public_state=sink.state,
    )
)
app.include_router(review_router(review, reviewer=reviewer), prefix="/admin")
```

[Drafts in storage](drafts.md) shows the imports and a full example.

## Notes for each project

### eesd-mmsdb

eesd-mmsdb is the reference adoption.

- Store: `FolderDraftStore`. It is close to the current folder with
  `info.json`.
- E-mail: `on_submit` sends the admin e-mail at upload.
- Contributor: the form sends a JSON `contributor` field with its own
  model.
- Status page: `public_state=sink.state` with `make_id=secret_id`.
  Only the contributor knows the ID.
- Publication stays manual. `on_publish` can copy the files to a
  staging folder.
- Step 9 also closes the open code scanning alerts on the current
  routes.

### hobel-iaqdb

- Store: an S3 `DraftStore`, built on `enacit4r_files`. It replaces
  `tmp/`, `draft/<id>/` and the `study_draft` table.
- `on_publish`: the current publish, the copy to `pub/` and the load
  into TimescaleDB.
- Validator: the Excel template parse stays in the validator. Today the
  data load runs after publication, so its errors show late. Move the
  CSV checks into the validator to show them at upload.

### ALICE-ETHZ-AREMA

- The draft is the entity row, not an uploaded file. Write a database
  `DraftStore` that reads and writes these rows.
- `on_publish`: the index into Elasticsearch. `on_withdraw`: the
  removal from the index.
- Reviewer: a dependency that checks its Keycloak roles.
- `Review` and its log replace the current state switch. ALICE has more
  states than `TRANSITIONS`. Map them before step 7. This is the
  largest change of the three.

## Next step

Make the inventory of step 1, then read [Testing](testing.md) to test
the new routes before you delete the old ones.
