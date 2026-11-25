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
| githubkit 0.17                                                    | No: the extra stops before 0.13          | 0.6.0: up to 0.17    |
| Trailers `Submitted-by`, `Institution`, `ORCID`                   | Yes                                      | Same format          |
| Trailers `GitHub`, `Dismissed-Warning`, `Verified-by`             | No                                       | Stays in resslab-hub |
| No `Institution` trailer for an empty field                       | No: the library always writes it         | Roadmap              |
| Role from the GitHub permission on the data repository            | `permission` gives the exact role        | resslab-hub maps it  |
| Review requests to the repository admins                          | `request_reviewers`                      | Same concept         |
| Edit an open contribution: a new commit on the same pull request  | No                                       | Roadmap              |
| Verification pull requests that change a status column           | No                                       | Stays in resslab-hub |
| Rows merged into the main CSV inside the pull request             | No: the library writes `submissions/`    | Roadmap              |
| Duplicate identifiers against the data repository                 | No                                       | Roadmap              |
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

## Roadmap after 0.6.0

1. Edit a contribution: add a commit to the branch of an open pull
   request. If the branch moved, refuse the update.
2. A table merge: add the rows of a contribution to the main CSV in the
   pull request, as an option of `GitHubPRSink`.
3. Duplicate identifiers: a validator helper that reads the identifiers of
   the main CSV on the base branch.
4. Optional trailers: leave out an empty field, and accept extra
   trailers from the project.

## Next step

Read the pull request of version 0.6.0. Then read the draft pull
request in resslab-hub that calls `commit_tree`.
