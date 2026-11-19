---
status: research
last_updated: 2026-11-19
summary: How five ENAC IT4R projects take data contributions, and the parts they share.
---

# Data contribution pipelines in five projects

This note compares how five projects take new data from outside contributors.
It is the basis for the design of `enacit4r-contrib`. Each claim cites the
source file. The study read the repositories on 2026-11-19. A claim marked
"(inference)" was not checked by running the code.

## Summary

All five projects do the same four steps. Only the tools differ:

1. Intake: take files from a browser (a folder, loose files or an archive)
   and keep only safe, expected paths.
2. Validation: report problems in one format, per file, row and column.
3. Sink: store the contribution where a person can review it.
4. Decision: a person accepts or rejects it, and the accepted data is
   published.

The projects use two patterns:

| | A. Draft in storage | B. Pull request |
| --- | --- | --- |
| Projects | hobel-iaqdb, ALICE-ETHZ-AREMA, eesd-mmsdb | resslab-hub, eesd-modern-masonry-walls-db |
| Sink | S3 draft (hobel), Postgres row (ALICE), local folder (mmsdb) | A branch and a pull request, through a GitHub App |
| Decision | An admin endpoint and a state | A GitHub review and merge |
| Publication | Ingestion into Postgres or Elasticsearch | A merge, then CI or a person loads the data |
| Record | DB rows | Git history, with commit trailers for provenance |

## Per project

### resslab-hub (pattern B, most complete)

- Intake in the browser (`frontend/src/utils/intake.ts`) and a tar.gz to
  the backend (`frontend/src/utils/tar.ts`).
- Validation in the browser (`utils/validation.ts`) and the backend
  (`backend/resslab_hub/data/validator.py`). The rules are in code and in the
  ORM models. Issue #366 proposes a rules file.
- The sink commits with the Git Data API through a GitHub App
  (`contributions/github.py:351-435`). It opens a pull request
  (`contributions/submission.py:505-569`) and records the contributor in
  commit trailers (`contributions/trailers.py`).
- The decision is a GitHub review under a ruleset. The merge starts
  `upload.yml` in the data repository, which loads the rows into Postgres.
- Gaps: text files only (no binary, no LFS), and it needs a server to hold
  the App key.

### eesd-modern-masonry-walls-db (pattern B, this library's first user)

- A static site. EESD's xlsx is the master copy of the dataset, so a
  contribution cannot go straight into `frontend/public/data/`.
- A contribution lands in `submissions/<id>/` on a new branch, with the
  starter-kit layout. The curator moves it into the xlsx for the next
  delivery.

### hobel-iaqdb (pattern A)

- Upload to `tmp/`, then a draft in S3 at `draft/<id>/`, with a DB row
  (`services/study_draft.py`).
- Validation at three moments: Excel parse (advisory), publish (pydantic),
  and after publish for measurement CSVs (`services/measurement.py`).
- The publish action is admin only. It copies `draft/` to `pub/` and loads
  the data into TimescaleDB in a background task.
- There are no review states. It already uses the shared `enacit4r_files`
  library for S3.

### ALICE-ETHZ-AREMA (pattern A, editorial)

- Entities in Postgres with a state machine: draft, in-review, to-publish,
  and more (`backend/api/services/entity.py:45-128`). Keycloak roles control
  each transition.
- Publication writes to Elasticsearch. The public site reads only
  Elasticsearch.
- There is no tabular validation, only pydantic types.

### eesd-mmsdb (pattern A, minimal)

- An anonymous upload goes to a local folder `<uuid>/` with an `info.json`.
  The admins get an email (`backend/api/views/files.py:205-230`).
- Only the file extensions are checked. Publication is a manual git and LFS
  procedure (`README.md:41-97`).

## What the library shares, and what stays in each project

The library holds:

- `Issue` and `Report`: the one problem format for every stage.
- `bundle.read_upload`: safe intake of files and archives, with a path
  allowlist.
- `Pipeline`: run the validator, refuse when the review queue is full, submit.
- `Sink`: the seam between the two patterns. `GitHubPRSink` is pattern B.
- `GitHubRepo`: the GitHub App client, binary-safe.
- `trailers`: provenance in commit messages.

Each project keeps:

- Its validator. The rules differ in all five projects, so the library gives
  a plug-in point (`Validator`), not a schema language.
- Its decision step and its publication: a merge workflow, an ingestion job,
  or an indexing job.

## Pattern A in the library

Version 0.3.0 adds pattern A to the library (`enacit4r_contrib.drafts`):

- `DraftSink` and a `DraftStore` keep each contribution as a draft. The
  library gives a folder store. A project can write an S3 store.
- `Review` moves a draft through submitted, accepted, rejected and
  published, with a log of each decision. It calls the project's publish
  hook (a database load or an index update) before it records "published".
- `review_router` gives the reviewer endpoints. The project gives the
  login check.

The transition table follows ALICE's flow (`entity.py:45-128`), with the
decision log that ALICE does not have. The page "Drafts in storage" tells
how each project maps onto these parts.
