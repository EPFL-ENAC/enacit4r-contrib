"""Who signs in, through Keycloak, and who can review.

    kc = KeycloakService(url, "external", client_id, client_secret, "admin")
    login = keycloak_github_login(kc.get_payload(required=False))
    app.include_router(review_router(review, reviewer=github_reviewer(repo, login)))

The library does no OAuth: the project validates the token (with
enacit4r-auth, for example) and gives the result as a FastAPI dependency.
"""

import time
from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException

from enacit4r_contrib.repo import ROLES, Permissions

CACHE_SECONDS = 60


def github_reviewer(
    repo: Permissions,
    login: Callable[..., Awaitable[str | None] | str | None],
    *,
    minimum: str = "write",
) -> Callable[..., Awaitable[str]]:
    """A `reviewer` dependency for `review_router`: the GitHub login of a user
    with at least `minimum` on the repository. 401 when `login` gives no
    login, 403 when the role is lower."""
    if minimum not in ROLES:
        raise ValueError(f"minimum must be one of {ROLES}, got {minimum!r}")
    # Roles stay in this process for 60 s: a removed collaborator can still
    # review for up to 60 s, and each replica keeps its own cache.
    cache: dict[str, tuple[float, str]] = {}

    async def reviewer(who: str | None = Depends(login)) -> str:
        if not who:
            raise HTTPException(401, "Sign in with GitHub to review")
        now = time.monotonic()
        hit = cache.get(who)
        if hit and hit[0] > now:
            role = hit[1]
        else:
            role = await repo.permission(who)
            cache[who] = (now + CACHE_SECONDS, role)
        # A custom role name is not in ROLES: treat it as "none".
        if (ROLES.index(role) if role in ROLES else 0) < ROLES.index(minimum):
            raise HTTPException(403, f"Needs {minimum} access to the data repository")
        return who

    return reviewer


def keycloak_github_login(
    get_payload_dependency: Callable, claim: str = "github_login"
) -> Callable[..., str | None]:
    """A dependency that reads the GitHub login from the token claims.
    Give it `kc_service.get_payload(required=False)`: no token gives None."""

    def login(payload: dict | None = Depends(get_payload_dependency)) -> str | None:
        return (payload or {}).get(claim) or None

    return login
