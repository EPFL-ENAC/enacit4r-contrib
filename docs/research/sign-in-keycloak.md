# Sign-in with Keycloak: study notes

These notes record the study behind issue 1 of this repository. They
tell what exists, what the maintainers decided, and which questions
stay open. The how-to is on the page [Sign in with Keycloak](../sign-in.md).

## What exists

- Keycloak on `https://enac-it-sso2.epfl.ch` has the `realm` `external`.
  This `realm` has GitHub as an identity provider.
- `enacit4r-auth` 0.8.0 gives
  `KeycloakService(url, realm, client_id, client_secret, admin_role, client_roles=False)`.
  It validates a Bearer token with the public key of the `realm`.
- `KeycloakService` gives FastAPI dependency factories:
  `get_payload(required=True)` (the raw claims of the token),
  `get_user_info(required=True)`, `require_role`, `require_any_role`
  and `require_admin`.
- `get_user_info` returns a `User` with `id`, `username`
  (`preferred_username`), `email`, `first_name`, `last_name` and
  `roles`. If nobody signed in and `required` is False, it returns None.
  `User` needs `email`, `first_name` and `last_name`.
- GitHub gives
  `GET /repos/{owner}/{repo}/collaborators/{username}/permission`.
  The field `permission` holds the legacy roles `admin`, `write`,
  `read` and `none`. The field `role_name` holds the exact role, for
  example `maintain` or `triage`. If the user is not a collaborator,
  the response is 404.

## Decisions

| Question                          | Decision                                   |
| --------------------------------- | ------------------------------------------ |
| Does the library do OAuth?        | No. The project signs in users with Keycloak |
| Who can review?                   | A user with write access on the data repository |
| Must a contributor sign in?       | No. Sign-in is optional                    |
| Which claim holds the GitHub login? | `github_login`, from a Keycloak mapper   |

The library reads the role through the GitHub App of the project. It
keeps each role in memory for 60 seconds.

## Open questions

1. Which `realm` must each project use: `external`, or a `realm` of its
   own?
2. OPS must add the `github_login` mapper to the GitHub provider. The
   name of the claim is a proposal.
3. A GitHub account can hide its e-mail address or have no name. Then
   `User` of `enacit4r-auth` cannot hold that user. Keycloak can ask
   for the missing values at the first sign-in. OPS must check this.
4. The Metadata read permission of the App can be sufficient for the
   collaborator endpoint. Each project must check this on its App.

## Next step

Read [Sign in with Keycloak](../sign-in.md) to wire the adapters in
your project.
