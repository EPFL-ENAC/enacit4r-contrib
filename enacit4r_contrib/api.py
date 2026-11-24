"""FastAPI router: the two HTTP endpoints of a data contribution.

    app.include_router(contribution_router(pipeline, allow=["02_fd_curve/*.csv"]))

Both endpoints take multipart/form-data. Each upload part is field `files`; its
filename carries the relative path ("masonry_walls/02_fd_curve/fd_curve_X.csv").
`allow` globs match after read_upload strips a top folder shared by all files.
"""

import json
import logging
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError
from starlette.datastructures import UploadFile

from enacit4r_contrib.bundle import BundleError, read_upload
from enacit4r_contrib.issues import Report
from enacit4r_contrib.pipeline import Contributor, Pipeline, QueueFull

log = logging.getLogger(__name__)

CHUNK = 2**20


def default_client_key(request: Request) -> str:
    """The last X-Forwarded-For entry (appended by our ingress), else the peer."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def _detail(status: int, detail) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status)


def _no_identity() -> None:
    return None


def contribution_router(
    pipeline: Pipeline,
    *,
    enabled: bool = True,
    allow: list[str],
    skip: list[str] = (),
    rate_limit: tuple[int, int] = (10, 3600),
    client_key: Callable[[Request], str] = default_client_key,
    max_files: int = 500,
    max_file_bytes: int = 50 * 2**20,
    max_total_bytes: int = 200 * 2**20,
    contributor: type[BaseModel] = Contributor,
    public_state: Callable[[str], Awaitable[str | None]] | None = None,
    ignore_case: bool = False,
    identity: Callable | None = None,
) -> APIRouter:
    """POST /validate checks an upload; POST /contributions submits it.

    enabled=False: POST /contributions answers 503, /validate still works.
    contributor: the model built from the form fields that it declares, or from
    one JSON form field `contributor`. A sink can need the `Contributor` fields.
    public_state: adds GET /contributions/{id}/state, which returns only the state.
    ignore_case: `allow` and `skip` globs match in any case.
    identity: a FastAPI dependency that returns the verified fields of a
    signed-in contributor (for example "name" and "email"), or None. Its
    values replace the same fields of the form.
    """
    router = APIRouter()
    max_attempts, window = rate_limit
    # Sliding window kept in this process: lost on restart, and not shared
    # between replicas (several replicas need a shared store such as Redis).
    # Keys are never dropped, so memory grows with distinct clients.
    attempts: dict[str, deque[float]] = defaultdict(deque)

    async def read_files(form) -> tuple[dict, list]:
        """Read every `files` part in chunks, refusing past the byte caps."""
        items: list[tuple[str, bytes]] = []
        total = 0
        for part in form.getlist("files"):
            if not isinstance(part, UploadFile):
                raise BundleError("Field 'files' must hold file uploads")
            name = part.filename or ""
            chunks: list[bytes] = []
            size = 0
            # Starlette spools each part to a temp file before this loop reads
            # it: cap the request body at the ingress to bound disk use too.
            while chunk := await part.read(CHUNK):
                size += len(chunk)
                total += len(chunk)
                if size > max_file_bytes:
                    raise BundleError(
                        f"File too large: {name} (max {max_file_bytes} bytes)"
                    )
                if total > max_total_bytes:
                    raise BundleError(f"Upload too large (max {max_total_bytes} bytes)")
                chunks.append(chunk)
            items.append((name, b"".join(chunks)))
        return read_upload(
            items,
            allow=allow,
            skip=skip,
            max_files=max_files,
            max_file_bytes=max_file_bytes,
            max_total_bytes=max_total_bytes,
            ignore_case=ignore_case,
        )

    def read_contributor(form, verified: dict | None) -> BaseModel:
        """Raise ValidationError or ValueError when the fields are not valid."""
        if isinstance(raw := form.get("contributor"), str):
            values = json.loads(raw)
            if not isinstance(values, dict):
                raise ValueError("Field 'contributor' must hold a JSON object")
        else:
            values = {
                k: v
                for k in contributor.model_fields
                if isinstance(v := form.get(k), str)
            }
        values = {**values, **(verified or {})}
        # A blank optional input arrives as "": treat it as absent.
        return contributor(
            **{
                k: v
                for k, v in values.items()
                if k in contributor.model_fields
                and v is not None
                and not (
                    isinstance(v, str)
                    and not v.strip()
                    and not contributor.model_fields[k].is_required()
                )
            }
        )

    @router.post("/validate")
    async def validate(request: Request):
        async with request.form(max_files=max_files) as form:
            try:
                bundle, issues = await read_files(form)
            except BundleError as e:
                return _detail(400, str(e))
        if bundle:
            try:
                issues += (await pipeline.check(bundle)).issues
            except Exception:
                log.exception("validator failed")
                return _detail(503, "The files cannot be checked now. Try again later.")
        return Report(issues).to_dict()

    @router.post("/contributions", status_code=201)
    async def contribute(
        request: Request, verified: dict | None = Depends(identity or _no_identity)
    ):
        if not enabled:
            return _detail(503, "Contributions are not open yet")
        key = client_key(request)
        now = time.monotonic()
        seen = attempts[key]
        while seen and seen[0] <= now - window:
            seen.popleft()
        if len(seen) >= max_attempts:
            return _detail(429, "Too many contributions from you. Try again later.")

        async with request.form(max_files=max_files) as form:
            try:
                person = read_contributor(form, verified)
            except ValidationError as e:
                return _detail(422, json.loads(e.json(include_url=False)))
            except ValueError as e:  # json.JSONDecodeError is a ValueError
                return _detail(422, str(e))
            try:
                bundle, issues = await read_files(form)
            except BundleError as e:
                return _detail(400, str(e))

        intake = Report(issues)
        if not intake.valid:
            return JSONResponse(intake.to_dict(), status_code=422)
        # Re-check after the awaits above: parallel requests passed the first check.
        if len(seen) >= max_attempts:
            return _detail(429, "Too many contributions from you. Try again later.")
        seen.append(now)
        try:
            report, receipt = await pipeline.submit(bundle, person, issues)
        except QueueFull:
            return _detail(
                429, "Too many contributions wait for review. Try again later."
            )
        except Exception:
            log.exception("contribution submit failed")
            return _detail(
                502, "Could not open the review request. Nothing was submitted."
            )
        if receipt is None:
            return JSONResponse(report.to_dict(), status_code=422)
        return {**report.to_dict(), "id": receipt.id, "url": receipt.url}

    if public_state is not None:

        @router.get("/contributions/{id}/state")
        async def contribution_state(id: str):
            state = await public_state(id)
            if state is None:
                return _detail(404, "No such contribution")
            return {"id": id, "state": state}

    return router
