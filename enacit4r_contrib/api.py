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
from collections.abc import Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.datastructures import UploadFile

from enacit4r_contrib.bundle import BundleError, read_upload
from enacit4r_contrib.issues import Report
from enacit4r_contrib.pipeline import Contributor, Pipeline, QueueFull

log = logging.getLogger(__name__)

CHUNK = 2**20
CONTRIBUTOR_FIELDS = ("name", "email", "institution", "orcid", "note")
OPTIONAL_FIELDS = ("orcid", "note")


def default_client_key(request: Request) -> str:
    """The last X-Forwarded-For entry (appended by our ingress), else the peer."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def _detail(status: int, detail) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status)


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
) -> APIRouter:
    """POST /validate checks an upload; POST /contributions submits it.

    enabled=False: POST /contributions answers 503, /validate still works.
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
    async def contribute(request: Request):
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
            # A blank optional input arrives as "": treat it as absent.
            fields = {
                k: v
                for k in CONTRIBUTOR_FIELDS
                if isinstance(v := form.get(k), str)
                and (v.strip() or k not in OPTIONAL_FIELDS)
            }
            try:
                contributor = Contributor(**fields)
            except ValidationError as e:
                return _detail(422, json.loads(e.json(include_url=False)))
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
            report, receipt = await pipeline.submit(bundle, contributor, issues)
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

    return router
