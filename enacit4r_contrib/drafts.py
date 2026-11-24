"""Pattern A: each contribution waits as a draft in storage for an admin decision.

store = FolderDraftStore(Path("/data/drafts"))
app.include_router(contribution_router(Pipeline(validate, DraftSink(store)), ...))
app.include_router(review_router(Review(store, on_publish=load), reviewer=admin))
"""

import json
import logging
import os
import secrets
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import Path
from typing import Protocol

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from enacit4r_contrib.issues import Issue, Report
from enacit4r_contrib.pipeline import Bundle, Contributor, Receipt
from enacit4r_contrib.sinks import slug

log = logging.getLogger(__name__)


class State(str, Enum):
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PUBLISHED = "published"
    WITHDRAWN = "withdrawn"


TRANSITIONS: dict[State, set[State]] = {
    State.SUBMITTED: {State.ACCEPTED, State.REJECTED},
    State.ACCEPTED: {State.PUBLISHED, State.REJECTED},
    State.PUBLISHED: {State.WITHDRAWN},
}
"""The allowed moves: from a state to the states it can go to."""


class TransitionError(Exception):
    """The draft cannot go from its state to the requested one."""


@dataclass
class Decision:
    state: State
    by: str
    at: str  # ISO 8601, UTC
    comment: str | None = None


@dataclass
class Draft:
    id: str
    state: State
    contributor: BaseModel  # Contributor, or the model given to the store
    report: Report
    files: list[str]
    history: list[Decision] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "state": self.state.value,
            "contributor": self.contributor.model_dump(),
            "report": self.report.to_dict(),
            "files": self.files,
            "history": [{**asdict(d), "state": d.state.value} for d in self.history],
        }

    @classmethod
    def from_dict(cls, d: dict, contributor: type[BaseModel] = Contributor) -> "Draft":
        return cls(
            id=d["id"],
            state=State(d["state"]),
            contributor=contributor(**d["contributor"]),
            report=Report([Issue(**i) for i in d["report"]["issues"]]),
            files=d["files"],
            history=[
                Decision(**{**h, "state": State(h["state"])}) for h in d["history"]
            ],
        )


class DraftStore(Protocol):
    async def save(self, draft: Draft, bundle: Bundle | None) -> None:
        """Write the draft. A bundle of None keeps the stored files."""
        ...

    async def load(self, id: str) -> Draft:
        """Raise KeyError when the draft does not exist."""
        ...

    async def files(self, id: str) -> Bundle: ...

    async def list(self, state: State | None = None) -> "list[Draft]": ...


def _check_id(id: str) -> str:
    if id in ("", ".", "..") or any(c in id for c in "/\\\x00"):
        raise KeyError(id)
    return id


class FolderDraftStore:
    """One folder per draft: `<root>/<id>/draft.json` and `<root>/<id>/files/`."""

    def __init__(self, root: Path, *, contributor: type[BaseModel] = Contributor):
        self.root = Path(root)
        self.contributor = contributor

    async def save(self, draft: Draft, bundle: Bundle | None) -> None:
        folder = self.root / _check_id(draft.id)
        for path, data in (bundle or {}).items():
            target = folder / "files" / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        folder.mkdir(parents=True, exist_ok=True)
        # Write draft.json last and atomically: a reader sees the old or the new file.
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=".draft-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(draft.to_dict(), f, indent=2)
            os.replace(tmp, folder / "draft.json")
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    async def load(self, id: str) -> Draft:
        path = self.root / _check_id(id) / "draft.json"
        try:
            return Draft.from_dict(json.loads(path.read_text()), self.contributor)
        except FileNotFoundError:
            raise KeyError(id) from None

    async def files(self, id: str) -> Bundle:
        draft = await self.load(id)
        base = self.root / id / "files"
        return {p: (base / p).read_bytes() for p in draft.files}

    async def list(self, state: State | None = None) -> list[Draft]:
        if not self.root.exists():
            return []
        drafts = [
            Draft.from_dict(json.loads(p.read_text()), self.contributor)
            for p in sorted(self.root.glob("*/draft.json"))
        ]
        return [d for d in drafts if state is None or d.state == state]


def secret_id(contributor: BaseModel | None = None) -> str:
    """A random id of 128 bits (22 URL-safe characters). Use it as `make_id`
    when the id gives access to the state of the draft."""
    return secrets.token_urlsafe(16)


class DraftSink:
    """A `Sink` that saves each contribution as a draft in SUBMITTED.

    make_id: builds the draft id. The default is `YYYY-MM-DD-<name slug>-<6 hex>`.
    on_submit: awaited after the draft is saved. Its errors are logged only.
    """

    def __init__(
        self,
        store: DraftStore,
        *,
        today: Callable[[], date] = date.today,
        make_id: Callable[[BaseModel], str] | None = None,
        on_submit: Callable[[Draft], Awaitable[None]] | None = None,
    ):
        self.store = store
        self.today = today
        self.make_id = make_id or self._dated_id
        self.on_submit = on_submit

    def _dated_id(self, contributor: BaseModel) -> str:
        name = slug(getattr(contributor, "name", "") or "")
        return f"{self.today():%Y-%m-%d}-{name}-{secrets.token_hex(3)}"

    async def submit(
        self, bundle: Bundle, contributor: Contributor, report: Report
    ) -> Receipt:
        id_ = self.make_id(contributor)
        draft = Draft(id_, State.SUBMITTED, contributor, report, list(bundle))
        await self.store.save(draft, bundle)
        if self.on_submit:
            try:
                await self.on_submit(draft)
            except Exception:
                # The draft is saved: a failed notice must not undo it.
                log.exception("on_submit failed for draft %s", id_)
        return Receipt(id_, "")

    async def state(self, id: str) -> str | None:
        """The state of the draft, or None when it does not exist."""
        try:
            return (await self.store.load(id)).state.value
        except KeyError:
            return None

    async def open_count(self) -> int:
        return sum(
            d.state in (State.SUBMITTED, State.ACCEPTED)
            for d in await self.store.list()
        )


class Review:
    """The decision step: move a draft along TRANSITIONS and record who did it."""

    def __init__(
        self,
        store: DraftStore,
        *,
        on_publish: Callable[[Draft, Bundle], Awaitable[None]] | None = None,
        on_change: Callable[[Draft, Decision], Awaitable[None]] | None = None,
        on_withdraw: Callable[[Draft], Awaitable[None]] | None = None,
    ):
        self.store = store
        self.on_publish = on_publish
        self.on_withdraw = on_withdraw
        self.on_change = on_change

    async def decide(
        self, id: str, to: State, by: str, comment: str | None = None
    ) -> Draft:
        draft = await self.store.load(id)
        to = State(to)
        if to not in TRANSITIONS.get(draft.state, set()):
            raise TransitionError(f"Cannot go from {draft.state.value} to {to.value}")
        if to == State.REJECTED and not (comment and comment.strip()):
            raise ValueError("A rejection needs a comment")
        if to == State.WITHDRAWN and not (comment and comment.strip()):
            raise ValueError("A withdrawal needs a comment")
        if to == State.PUBLISHED and self.on_publish:
            # The hook runs first: if it fails, the draft stays accepted.
            await self.on_publish(draft, await self.store.files(id))
        if to == State.WITHDRAWN and self.on_withdraw:
            # The hook runs first: if it fails, the draft stays published.
            await self.on_withdraw(draft)
        decision = Decision(to, by, datetime.now(UTC).isoformat(), comment)
        draft.state = to
        draft.history.append(decision)
        await self.store.save(draft, None)
        if self.on_change:
            try:
                await self.on_change(draft, decision)
            except Exception:
                # The decision is saved: a failed notice must not undo it.
                log.exception("on_change failed for draft %s", id)
        return draft


class DecisionIn(BaseModel):
    state: State
    comment: str | None = None


def review_router(review: Review, *, reviewer: Callable[..., str]) -> APIRouter:
    """The admin endpoints. `reviewer` is a FastAPI dependency: it returns the
    reviewer's name, or raises HTTPException(401 or 403)."""
    router = APIRouter(dependencies=[Depends(reviewer)])
    store = review.store

    async def load(id: str) -> Draft:
        try:
            return await store.load(id)
        except KeyError:
            raise HTTPException(404, "No such draft") from None

    @router.get("/drafts")
    async def list_drafts(state: State | None = None):
        return [d.to_dict() for d in await store.list(state)]

    @router.get("/drafts/{id}")
    async def get_draft(id: str):
        return (await load(id)).to_dict()

    @router.get("/drafts/{id}/files/{path:path}")
    async def get_file(id: str, path: str):
        await load(id)
        data = (await store.files(id)).get(path)
        if data is None:
            raise HTTPException(404, "No such file")
        # The bytes come from a contributor: never let the browser render them.
        return Response(data, media_type="application/octet-stream")

    @router.post("/drafts/{id}/decision")
    async def decide(id: str, body: DecisionIn, by: str = Depends(reviewer)):
        try:
            draft = await review.decide(id, body.state, by, body.comment)
        except KeyError:
            raise HTTPException(404, "No such draft") from None
        except TransitionError as e:
            return JSONResponse({"detail": str(e)}, status_code=409)
        except ValueError as e:
            return JSONResponse({"detail": str(e)}, status_code=422)
        except Exception:
            if body.state == State.WITHDRAWN:
                log.exception("withdrawal of draft %s failed", id)
                detail = "Withdrawal failed. The draft stays published."
            else:
                log.exception("publication of draft %s failed", id)
                detail = "Publication failed. The draft stays accepted."
            return JSONResponse({"detail": detail}, status_code=502)
        return draft.to_dict()

    return router
