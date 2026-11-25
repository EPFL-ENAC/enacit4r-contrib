# resslab-hub on the library: gap study

This study compares the contribution code of resslab-hub with the
library at version 0.5.0. It tells which parts resslab-hub can give to
the library now, which parts need a new version, and which parts stay
in resslab-hub. Read it before you plan version 0.6.0.

resslab-hub is AGPL and the library is MIT. The library team wrote this
study from the behavior of resslab-hub, not from its code. A library
feature that comes from this list starts from a written specification.
The builder of that feature does not read the resslab-hub code.

## What resslab-hub does

resslab-hub takes contributions of nine data types. A contributor
uploads a `.tar.gz` file. The backend validates it and opens a pull
request on a separate data repository through a GitHub App. Curators
review the pull requests in a page of the hub. After the merge, a
workflow of the data repository loads the changed files into Postgres.

## Feature map

| resslab-hub feature                                               | Library 0.5.0                            | Plan                 |
| ----------------------------------------------------------------- | ---------------------------------------- | -------------------- |
| One commit through the Git Data API, blobs uploaded in parallel   | `create_branch_commit`                   | Same concept         |
| A commit on any parent, with deletions, and no move of a branch   | No                                       | 0.6.0: `commit_tree` |
| Skip the upload of a file that is already on the branch           | No                                       | 0.6.0: `commit_tree` |
| The contributor as the commit author                              | No: the App is the author                | 0.6.0: `author=`     |
| One shared HTTP client for the full process                       | No: each `GitHubRepo` makes its client   | 0.6.0: `github=`     |
| githubkit 0.17                                                    | No: the extra stops before 0.13          | 0.6.0: 0.17.1        |
| Trailers `Submitted-by`, `Institution`, `ORCID`                   | Yes                                      | Same format          |
| Trailers `GitHub`, `Dismissed-Warning`, `Verified-by`             | No                                       | Stays in resslab-hub |
| No `Institution` trailer for an empty field                       | No: the library always writes it         | 0.6.0: `format_trailers` |
| Role from the GitHub permission on the data repository            | `permission` gives the exact role        | resslab-hub maps it  |
| Review requests to the repository admins                          | `request_reviewers`                      | Same concept         |
| Edit an open contribution: a new commit on the same pull request  | No                                       | 0.6.0: `commit_on_branch` |
| Verification pull requests that change a status column           | No                                       | Stays in resslab-hub |
| Rows merged into the main CSV inside the pull request             | No: the library writes `submissions/`    | 0.6.0: `TableMerge`  |
| Duplicate identifiers against the data repository                 | No                                       | 0.6.0: `table_ids`   |
| A curation queue built from the open pull requests                | No                                       | Stays in resslab-hub |
| Safe extraction of a `.tar.gz` to a folder                        | `read_upload`, in memory                 | Stays in resslab-hub |
| Sign-in with an e-mail code, GitHub and ORCID                     | No: Keycloak does sign-in                | Stays in resslab-hub |
| Load into Postgres after the merge                                | `ingest` action, project code loads      | Stays in resslab-hub |

## Why the first step is small

The resslab-hub tests drive its commit code through a fake of the Git
Data API. A swap that changes the calls to GitHub breaks these tests.
Version 0.6.0 adds `commit_tree`, which makes the same calls: one blob
for each changed file, UTF-8 for text, one tree on the parent, one
commit. resslab-hub can then give its commit code to the library and
keep its tests.

The intake stays in resslab-hub. Its extraction writes to a folder and
its validators read that folder. `read_upload` reads into memory, and a
swap brings no gain.

## Decisions for resslab-hub before the next steps

The maintainers of resslab-hub must make these decisions. Each one
changes what the library builds. On 2026-11-25 the maintainers
accepted the recommendation of each decision.

| Decision                                 | Options                                                                  | Recommendation                                                      |
| ---------------------------------------- | ------------------------------------------------------------------------ | ------------------------------------------------------------------- |
| D1. Where the rows go in the pull request | A: merged into the main CSV (today). B: `submissions/<id>/`, then ingest | A. The data repository, its checks and the curation page stay as they are |
| D2. Who is the commit author             | A: the contributor (today). B: the App, with the contributor in trailers | A. The library has `author=` for this                               |
| D3. Sign-in                              | A: the own sign-in of resslab-hub (today). B: Keycloak with GitHub       | A for this roadmap. Decide B in a separate study                    |
| D4. Intake and validators                | A: a folder (today). B: the in-memory `Bundle` of the library            | A. Only the GitHub layer moves to the library                       |
| D5. Release of the library               | A: a git tag (today). B: PyPI                                            | A. The backend image installs git in its build stage                |

If resslab-hub chooses B for D1, the data repository changes too: its
validation workflow, its `upload.yml` and the curation page read the
main CSV in the pull request today. That is a migration of the data
repository, not a library task.

## Roadmap

The six steps ship together in library 0.6.0, on one library branch and
one resslab-hub branch. After each step, the resslab-hub tests of the
GitHub client, the contributions and the curation pass with no edit.

1. The commit goes through `commit_tree`, with a shared client and the
   contributor as author.
2. The pull request, the review requests and the branch cleanup go
   through `GitHubRepo`. resslab-hub maps the exact role of
   `permission` to its base levels.
3. Trailers: resslab-hub writes and reads its trailers with
   `format_trailers`, `address`, `parse_trailers` and `split_address`.
4. Edit a contribution: `commit_on_branch` adds a commit to an open
   branch. If the branch moved, it raises `BranchMoved`, and
   resslab-hub answers 409, as before.
5. The table module merges the rows into the main CSV and finds the
   duplicate identifiers.
6. The read API (`open_pulls`, `pull_commits`, `pull_comments`,
   `list_dir`, `open_contributions`) feeds the curation queue.

The library requires githubkit 0.17.1, so the two adopters run the same
version.

These parts stay in resslab-hub: the verification pull
requests, the classification of the curation queue, the nine data
types and their validators, the sign-in, and the load into Postgres.
The verification pull requests use `commit_tree` and `open_pull` of the
library.

## Next step

Test the resslab-hub branch on the test fork of the data repository.
Then tag the library and pin resslab-hub to the tag.
