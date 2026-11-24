# Sign in with Keycloak

This page tells you how to connect the sign-in of your project to the
contribution form and to the review endpoints. The library does not
sign in users. Your project does that with Keycloak. The library adds
three small adapters that use the result.

## Why Keycloak and GitHub

The reviewers of a data set are the people who can change the data
repository on GitHub. Thus you do not keep a second list of users. If
you give a person write access on the repository, that person can
review. If you remove the access, the person cannot review after 60
seconds.

Sign-in is optional for contributors. If a contributor signs in, the
verified name and e-mail address replace the values of the form. If a
contributor does not sign in, the form works as before.

## The parts

| Part                    | Job                                                    |
| ----------------------- | ------------------------------------------------------ |
| Keycloak `realm` `external` | Signs in users on `https://enac-it-sso2.epfl.ch`   |
| GitHub provider         | Lets a user sign in to Keycloak with a GitHub account  |
| `github_login` mapper   | Puts the GitHub login of the user in the token         |
| `keycloak-js`           | Signs in the user in the frontend and sends the token  |
| `enacit4r-auth`         | Validates the token in the backend                     |
| The GitHub App          | Reads the role of the user on the data repository      |

The Keycloak `realm` `external` already has GitHub as an identity provider. The
claim `preferred_username` is not always the GitHub login. Ask OPS to
add an identity provider mapper to the GitHub provider. The mapper must
copy the GitHub login into a token claim with the name `github_login`.

## The adapters

The library gives these functions:

- `GitHubRepo.permission(login)` returns the role of a GitHub user on
  the repository: `admin`, `maintain`, `write`, `triage`, `read` or
  `none`.
- `github_reviewer(repo, login, minimum="write")` returns a `reviewer`
  dependency for `review_router`. If nobody signed in, it answers 401.
  If the role is lower than `minimum`, it answers 403.
- `keycloak_github_login(get_payload)` returns a dependency that reads
  the `github_login` claim. If there is no token, it returns None.

`github_reviewer` keeps each role in memory for 60 seconds. Each
replica of the backend keeps its own copy.

## Wire the backend

This example uses `enacit4r-auth` 0.8.0. `kc.get_payload` gives the
claims of the token. `kc.get_user_info` gives a `User` with the e-mail
address and the names.

```python
from fastapi import Depends
from enacit4r_auth.services.auth import KeycloakService, User

from enacit4r_contrib import contribution_router
from enacit4r_contrib.drafts import review_router
from enacit4r_contrib.github import GitHubRepo
from enacit4r_contrib.identity import github_reviewer, keycloak_github_login

kc = KeycloakService(url, "external", client_id, client_secret, "admin")
repo = GitHubRepo(
    "EPFL-ENAC/my-data",
    app_id=app_id,
    private_key=private_key,
    installation_id=installation_id,
)

reviewer = github_reviewer(repo, keycloak_github_login(kc.get_payload(required=False)))
app.include_router(review_router(review, reviewer=reviewer), prefix="/admin")


def identity(user: User | None = Depends(kc.get_user_info(required=False))):
    if user is None:
        return None
    name = f"{user.first_name} {user.last_name}".strip()
    return {"name": name, "email": user.email}


app.include_router(contribution_router(pipeline, allow=["*.csv"], identity=identity))
```

The `identity` dependency returns a dict or None. The keys of the dict
must be fields of the contributor model. If a contributor signs in,
these values replace the same fields of the form or of the JSON field
`contributor`.

## Wire the frontend

Use `keycloak-js` with the `realm` `external` and a public client. Call
`keycloak.init({ onLoad: "check-sso" })`, so that a page does not force
the sign-in. If `keycloak.authenticated` is true, send the token with
each request:

```javascript
headers: { Authorization: `Bearer ${keycloak.token}` }
```

The admin page must ask the user to sign in. The contribution form can
show a sign-in button, and keep the name and e-mail inputs for users
who do not sign in.

## Permissions of the GitHub App

`GitHubRepo.permission` calls
`GET /repos/{owner}/{repo}/collaborators/{username}/permission` with
the App from [GitHub App](github-app.md). The Metadata read permission
of the App can be sufficient for this endpoint. Check this on your
App: sign in, then open the admin page. If the response is 403 for a user
with write access, look at the log of the backend.

> Note: A user who is not a collaborator gets the role `none`. A
> member of an organization team with write access gets the role of
> the team.

## Limits

- `User` of `enacit4r-auth` needs an e-mail address, a first name and
  a last name. A GitHub account can hide its e-mail address or have no
  name. Then `kc.get_user_info` can fail for that user. Ask OPS to make
  Keycloak ask for the missing values at the first sign-in.
- If the `github_login` claim is missing, each reviewer gets 401. Read
  a token on jwt.io and make sure that the claim is there.

## Next step

Ask OPS for the `github_login` mapper on the `realm` `external`. Then
replace your `reviewer` dependency with `github_reviewer`, as in the
example above.
