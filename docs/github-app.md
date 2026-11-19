# GitHub App

`GitHubPRSink` needs credentials to push a branch and open a pull
request. This page tells you why to use a GitHub App, and how to
create one. At the end, you have the three settings that `GitHubRepo`
needs.

## Why an App and not a personal token

`GitHubRepo` also accepts a `token`. Do not use a personal token in
production, for these reasons:

- A personal token acts for one person. If that person leaves, the
  contributions stop.
- A personal token can access each repository of that person. An App
  can access only the repositories where you install it.
- An App uses tokens that expire after one hour. The library makes
  them from the private key.
- The pull request shows the App as the author. Thus the reviewers see
  that the pull request comes from the contribution form.

## Create the App

Do these steps as an owner of the EPFL-ENAC organization, or ask an
owner.

1. Open the settings of the organization. Go to Developer settings,
   then GitHub Apps, then New GitHub App.
2. In GitHub App name, write a unique name of 34 characters or less,
   for example `my-dataset-contributions`. The name shows as the
   author of each pull request.
3. In Homepage URL, write the URL of your site.
4. Keep Callback URL empty.
5. Under Webhook, clear Active.
6. Under Repository permissions, set these values:
    - Contents: Read and write.
    - Pull requests: Read and write.
    - Metadata: Read-only.
7. Keep No access for each other permission.
8. Under "Where can this GitHub App be installed?", select "Only on
   this account".
9. Click Create GitHub App.

## Get the three settings

1. On the page of the App, copy the App ID. This is the first setting.
2. Under Private keys, click Generate a private key. The browser
   downloads a `.pem` file. The content of this file is the second
   setting.
3. Click Install App, then Install for the organization.
4. Select Only select repositories, and select the data repository.
   Click Install.
5. Look at the URL of the page that opens. It ends with
   `/installations/<number>`. The number is the installation ID, the
   third setting.

> CAUTION: Do not commit the `.pem` file to a repository. Anyone with
> the key can write to the data repository. Put the key in the secret
> store of your deployment.

Give the three settings to `GitHubRepo`:

```python
import os

from enacit4r_contrib.github import GitHubRepo

repo = GitHubRepo(
    "EPFL-ENAC/my-dataset",
    app_id=os.environ["GITHUB_APP_ID"],
    private_key=os.environ["GITHUB_APP_PRIVATE_KEY"],
    installation_id=int(os.environ["GITHUB_APP_INSTALLATION_ID"]),
)
```

An environment variable often holds the key on one line, with `\n`
in place of each line break. `GitHubRepo` changes each `\n` back to a
line break. If you give only one or two of the three settings,
`GitHubRepo` raises `ValueError`.

## Who is the author

A contributor does not have a verified GitHub account. Thus the App is
the author of the commit and of the pull request. The library writes
the contributor in the trailers of the commit message:

```text
Data contribution from Ada Lovelace

Submitted-by: Ada Lovelace <ada@example.org>
Institution: EPFL
ORCID: 0000-0002-1825-0097
```

The git history keeps this record after the merge. The function
`enacit4r_contrib.trailers.parse_trailers` reads these lines back.

## Workflows on the pull request

If a workflow opens a pull request with the default `GITHUB_TOKEN`,
GitHub does not start other workflows on it. A pull request that an
App opens starts the workflows of the data repository. Thus your CI
can check each contribution before the review.

## Next step

Read [Sinks](sinks.md) to see what the sink writes in the repository.
