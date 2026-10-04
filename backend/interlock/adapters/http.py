"""FastAPI command boundary for the INTERLOCK application.

The adapter validates transport requests, appends canonical facts through the
composition root, and returns detached read projections.  It never mutates
``SessionState`` or treats journal acceptance as completion of downstream work.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from copy import deepcopy
from hashlib import sha256
import json
from typing import Annotated, Any, Literal, TypeVar

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints, model_validator

from interlock.domain.enums import (
    Authorization,
    DivergenceState,
    EventSource,
    IntentMaturity,
    PlanState,
    RuntimeMode,
    SpeechState,
)
from interlock.domain.models import EventEnvelope, SessionState
from interlock.main import Application
from interlock.runtime.journal import (
    DedupeConflictError,
    EventCandidate,
    JournalError,
    SchemaInvalidError,
    SessionHaltedError,
    UnknownSessionError,
)
from interlock.adapters.websocket import (
    ProjectionHub,
    event_message,
    project_state,
)
from interlock.runtime.session import generate_uuidv7


_CANONICAL_MODALITY: Mapping[str, str] = {
    "TEXT": "text",
    "FRAME_REF": "frame_ref",
    "AUDIO_REF": "audio_ref",
}

_RequestId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=256),
]
_Identifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=512),
]
_ResultT = TypeVar("_ResultT")


class _RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SessionCreateRequest(_RequestModel):
    mode: Literal["DEMO", "LIVE", "TEST"]
    client_request_id: _RequestId


class InputRequest(_RequestModel):
    modality: Literal["TEXT", "FRAME_REF", "AUDIO_REF"]
    content: str | None = None
    content_ref: str | None = None
    client_request_id: _RequestId

    @model_validator(mode="after")
    def validate_modality_content(self) -> "InputRequest":
        if self.modality == "TEXT":
            if self.content is None or not self.content.strip():
                raise ValueError("TEXT requires nonempty content")
            if self.content_ref is not None:
                raise ValueError("TEXT forbids content_ref")
        else:
            if self.content is not None:
                raise ValueError("reference modalities forbid inline content")
            if self.content_ref is None or not self.content_ref.strip():
                raise ValueError("reference modalities require content_ref")
        return self


class AuthorizationRequest(_RequestModel):
    revision_id: _Identifier | None = None
    plan_id: _Identifier | None = None
    decision: Literal["AUTHORIZE", "DENY"]
    client_request_id: _RequestId

    @model_validator(mode="after")
    def validate_exact_target(self) -> "AuthorizationRequest":
        if (self.revision_id is None) == (self.plan_id is None):
            raise ValueError("exactly one of revision_id or plan_id is required")
        return self


class SpeechCancelRequest(_RequestModel):
    client_request_id: _RequestId


class FaultRequest(_RequestModel):
    fault_id: _Identifier
    enabled: StrictBool


class ResetRequest(_RequestModel):
    fixture_id: Literal["samsung-demo-v1"]
    client_request_id: _RequestId


class _StoredRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    fingerprint: str
    response: dict[str, Any]


class _PendingRequest:
    def __init__(self, fingerprint: str) -> None:
        self.fingerprint = fingerprint
        self.future: asyncio.Future[tuple[bool, object]] = (
            asyncio.get_running_loop().create_future()
        )


class _HttpBoundary:
    """Bounded, adapter-local retry bookkeeping around one injected application."""

    def __init__(
        self,
        application: Application,
        *,
        max_input_bytes: int,
        max_dedupe_entries: int,
        event_page_size: int,
        reset_timeout_s: float,
    ) -> None:
        if max_input_bytes < 1 or max_dedupe_entries < 1 or event_page_size < 1:
            raise ValueError("HTTP adapter bounds must be positive")
        if reset_timeout_s <= 0:
            raise ValueError("reset_timeout_s must be positive")
        self.application = application
        self.max_input_bytes = max_input_bytes
        self.max_dedupe_entries = max_dedupe_entries
        self.event_page_size = event_page_size
        self.reset_timeout_s = reset_timeout_s
        self._accepted: OrderedDict[tuple[str, str, str], _StoredRequest] = OrderedDict()
        self._pending: dict[tuple[str, str, str], _PendingRequest] = {}
        self._dedupe_lock = asyncio.Lock()
        # Fixed lock striping keeps preflight + append atomic per session without
        # retaining an unbounded lock registry for retired session identities.
        self._command_locks = tuple(
            asyncio.Lock() for _ in range(max(1, min(application.max_sessions, 64)))
        )

    async def dedupe(
        self,
        key: tuple[str, str, str],
        request: BaseModel | Mapping[str, Any],
        operation: Callable[[], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        normalized = (
            request.model_dump(mode="json")
            if isinstance(request, BaseModel)
            else dict(request)
        )
        fingerprint = _fingerprint(normalized)
        owner = False
        async with self._dedupe_lock:
            stored = self._accepted.get(key)
            if stored is not None:
                if stored.fingerprint != fingerprint:
                    raise HTTPException(status.HTTP_409_CONFLICT, "conflicting client_request_id")
                self._accepted.move_to_end(key)
                return deepcopy(stored.response)
            pending = self._pending.get(key)
            if pending is not None:
                if pending.fingerprint != fingerprint:
                    raise HTTPException(status.HTTP_409_CONFLICT, "conflicting client_request_id")
            else:
                if len(self._pending) >= self.max_dedupe_entries:
                    raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "request capacity reached")
                pending = _PendingRequest(fingerprint)
                self._pending[key] = pending
                owner = True

        if not owner:
            succeeded, value = await pending.future
            if succeeded:
                return deepcopy(value)  # type: ignore[arg-type]
            raise value  # type: ignore[misc]

        try:
            if key[0] == "_application":
                response = await operation()
            else:
                stripe = int.from_bytes(
                    sha256(key[0].encode("utf-8")).digest()[:8], "big"
                ) % len(self._command_locks)
                async with self._command_locks[stripe]:
                    response = await operation()
        except BaseException as exc:
            async with self._dedupe_lock:
                self._pending.pop(key, None)
                if not pending.future.done():
                    pending.future.set_result((False, exc))
            raise

        detached = deepcopy(response)
        async with self._dedupe_lock:
            self._pending.pop(key, None)
            self._accepted[key] = _StoredRequest(
                fingerprint=fingerprint,
                response=detached,
            )
            self._accepted.move_to_end(key)
            while len(self._accepted) > self.max_dedupe_entries:
                self._accepted.popitem(last=False)
            if not pending.future.done():
                pending.future.set_result((True, detached))
        return deepcopy(detached)

    def snapshot(self, session_id: str) -> SessionState:
        try:
            return self.application.snapshot(session_id)
        except KeyError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found") from exc

    async def append(self, candidate: EventCandidate) -> EventEnvelope:
        try:
            return await self.application.append(candidate)
        except (KeyError, UnknownSessionError) as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found") from exc
        except DedupeConflictError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, "conflicting client_request_id") from exc
        except SchemaInvalidError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid canonical event") from exc
        except SessionHaltedError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, "session is unavailable") from exc
        except JournalError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, "event was not accepted") from exc
        except RuntimeError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, "session cannot accept input") from exc


def create_http_app(
    application: Application,
    *,
    hub: ProjectionHub | None = None,
    max_input_bytes: int = 65_536,
    max_dedupe_entries: int | None = None,
    event_page_size: int = 256,
    reset_timeout_s: float = 2.0,
) -> FastAPI:
    """Create the HTTP boundary around an existing application graph."""

    dedupe_bound = max_dedupe_entries or application.settings.INTERLOCK_EVENT_RETENTION
    boundary = _HttpBoundary(
        application,
        max_input_bytes=max_input_bytes,
        max_dedupe_entries=dedupe_bound,
        event_page_size=event_page_size,
        reset_timeout_s=reset_timeout_s,
    )
    app = FastAPI(title="INTERLOCK HTTP API", version="1")
    app.state.interlock_application = application
    app.state.interlock_hub = hub

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request, error: RequestValidationError
    ) -> JSONResponse:
        details = [
            {
                "loc": list(item.get("loc", ())),
                "type": item.get("type", "validation_error"),
                "msg": item.get("msg", "invalid request"),
            }
            for item in error.errors()
        ]
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": details})

    @app.get("/api/v1/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "mode": application.settings.INTERLOCK_MODE}

    @app.post("/api/v1/sessions", status_code=status.HTTP_201_CREATED)
    async def create_session(request: SessionCreateRequest) -> dict[str, Any]:
        async def start() -> dict[str, Any]:
            session_id = generate_uuidv7()
            try:
                snapshot = await application.start_session(session_id, mode=request.mode)
            except ValueError as exc:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid session request") from exc
            except RuntimeError as exc:
                raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "session capacity reached") from exc
            return {
                "session_id": session_id,
                "last_sequence": snapshot.last_sequence,
                "ws_url": _session_ws_url(application.settings.INTERLOCK_WS_URL, session_id),
            }

        return await boundary.dedupe(
            ("_application", "create_session", request.client_request_id), request, start
        )

    @app.get("/api/v1/sessions/{session_id}")
    async def get_session(session_id: str) -> dict[str, Any]:
        snapshot = boundary.snapshot(session_id)
        return {
            "session_id": session_id,
            "through_sequence": snapshot.last_sequence,
            "projection": project_state(snapshot),
        }

    @app.post(
        "/api/v1/sessions/{session_id}/inputs",
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def input_observed(session_id: str, request: InputRequest) -> dict[str, Any]:
        content_ref = request.content if request.modality == "TEXT" else request.content_ref
        assert content_ref is not None
        if len(content_ref.encode("utf-8")) > boundary.max_input_bytes:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "input exceeds configured size")

        async def accept() -> dict[str, Any]:
            boundary.snapshot(session_id)
            event = await boundary.append(EventCandidate(
                session_id=session_id,
                event_type="UserInputObserved",
                source=EventSource.INPUT_ADAPTER,
                payload={
                    "evidence_id": _stable_id("input", session_id, request.client_request_id),
                    "modality": _CANONICAL_MODALITY[request.modality],
                    "content_ref": content_ref,
                },
                correlation_id=request.client_request_id,
                dedupe_key=f"http:input:{request.client_request_id}",
            ))
            return _acceptance(event)

        return await boundary.dedupe(
            (session_id, "input", request.client_request_id), request, accept
        )

    @app.post(
        "/api/v1/sessions/{session_id}/authorizations",
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def authorization(session_id: str, request: AuthorizationRequest) -> dict[str, Any]:
        async def accept() -> dict[str, Any]:
            snapshot = boundary.snapshot(session_id)
            evidence_id = _stable_id("authorization", session_id, request.client_request_id)
            if request.revision_id is not None:
                _validate_revision_authorization(snapshot, request.revision_id, request.decision)
                event_type = "IntentAuthorizationChanged"
                payload = {
                    "revision_id": request.revision_id,
                    "authorization": (
                        Authorization.AUTHORIZED.value
                        if request.decision == "AUTHORIZE"
                        else Authorization.DENIED.value
                    ),
                    "evidence_id": evidence_id,
                }
            else:
                assert request.plan_id is not None
                _validate_plan_authorization(snapshot, request.plan_id)
                event_type = (
                    "ReconciliationAuthorized"
                    if request.decision == "AUTHORIZE"
                    else "ReconciliationDenied"
                )
                payload = {"plan_id": request.plan_id, "evidence_id": evidence_id}
                if request.decision == "DENY":
                    payload["reason"] = "user_denied"
            event = await boundary.append(EventCandidate(
                session_id=session_id,
                event_type=event_type,
                source=EventSource.USER,
                payload=payload,
                correlation_id=request.client_request_id,
                dedupe_key=f"http:authorization:{request.client_request_id}",
            ))
            return _acceptance(event)

        return await boundary.dedupe(
            (session_id, "authorization", request.client_request_id), request, accept
        )

    @app.post(
        "/api/v1/sessions/{session_id}/speech/{speech_id}/cancel",
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def cancel_speech(
        session_id: str, speech_id: str, request: SpeechCancelRequest
    ) -> dict[str, Any]:
        async def accept() -> dict[str, Any]:
            snapshot = boundary.snapshot(session_id)
            speech = snapshot.speech.get(speech_id)
            if speech is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "speech not found")
            if speech.state in {
                SpeechState.EMITTED.value,
                SpeechState.CANCELLED.value,
                SpeechState.BLOCKED.value,
                SpeechState.CORRECTION_REQUIRED.value,
            }:
                raise HTTPException(status.HTTP_409_CONFLICT, "speech is not cancellable")
            event = await boundary.append(EventCandidate(
                session_id=session_id,
                event_type="SpeechCancellationRequested",
                source=EventSource.USER,
                payload={"speech_id": speech_id},
                correlation_id=request.client_request_id,
                dedupe_key=f"http:speech-cancel:{request.client_request_id}",
            ))
            return _acceptance(event)

        return await boundary.dedupe(
            (session_id, f"speech_cancel:{speech_id}", request.client_request_id),
            request,
            accept,
        )

    @app.post(
        "/api/v1/sessions/{session_id}/demo/faults",
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def activate_fault(session_id: str, request: FaultRequest) -> dict[str, Any]:
        request_key = _stable_id("fault", request.fault_id, str(request.enabled))

        async def accept() -> dict[str, Any]:
            snapshot = boundary.snapshot(session_id)
            if snapshot.mode != RuntimeMode.DEMO.value:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "fault controls require DEMO mode")
            event = await boundary.append(EventCandidate(
                session_id=session_id,
                event_type="FaultActivated",
                source=EventSource.SCENARIO,
                payload={
                    "fault_id": request.fault_id,
                    "operation_match": {"enabled": request.enabled},
                },
                correlation_id=request_key,
                dedupe_key=f"http:fault:{request_key}",
            ))
            return _acceptance(event)

        return await boundary.dedupe((session_id, "fault", request_key), request, accept)

    @app.post("/api/v1/sessions/{session_id}/demo/reset")
    async def reset_demo(session_id: str, request: ResetRequest) -> dict[str, Any]:
        async def reset() -> dict[str, Any]:
            snapshot = boundary.snapshot(session_id)
            if snapshot.mode != RuntimeMode.DEMO.value:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "reset requires DEMO mode")
            try:
                await asyncio.wait_for(
                    application.close_session(session_id), timeout=boundary.reset_timeout_s
                )
            except (asyncio.TimeoutError, RuntimeError) as exc:
                raise HTTPException(status.HTTP_409_CONFLICT, "session could not be safely retired") from exc
            if hub is not None:
                await hub.retire_session(session_id, reason="RESET")
            new_session_id = generate_uuidv7()
            try:
                clean = await application.start_session(new_session_id, mode=RuntimeMode.DEMO)
            except (ValueError, RuntimeError) as exc:
                raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "new session unavailable") from exc
            return {"session_id": new_session_id, "last_sequence": clean.last_sequence}

        return await boundary.dedupe(
            (session_id, "reset", request.client_request_id), request, reset
        )

    @app.get("/api/v1/sessions/{session_id}/events")
    async def events(
        session_id: str,
        after_sequence: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int | None, Query(ge=1)] = None,
    ) -> dict[str, Any]:
        snapshot = boundary.snapshot(session_id)
        if after_sequence > snapshot.last_sequence:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "after_sequence is in the future")
        retained = [
            event
            for event in application.events(session_id)
            if event.sequence <= snapshot.last_sequence
        ]
        if retained and after_sequence < retained[0].sequence - 1:
            raise HTTPException(status.HTTP_410_GONE, "requested event history has expired")
        page_limit = min(limit or boundary.event_page_size, boundary.event_page_size)
        available = [event for event in retained if event.sequence > after_sequence]
        selected = available[:page_limit]
        through_sequence = selected[-1].sequence if selected else after_sequence
        return {
            "events": _serialize_events(
                application=application,
                session_id=session_id,
                selected=selected,
                after_sequence=after_sequence,
                all_retained=retained,
                hub=hub,
            ),
            "through_sequence": through_sequence,
            "has_more": len(available) > len(selected),
        }

    return app


def _validate_revision_authorization(
    state: SessionState, revision_id: str, decision: str
) -> None:
    revision = state.revisions.get(revision_id)
    if revision is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown revision target")
    active_revision_id = _active_revision_id(state)
    target = Authorization.AUTHORIZED.value if decision == "AUTHORIZE" else Authorization.DENIED.value
    if (
        active_revision_id != revision_id
        or revision.maturity == IntentMaturity.SUPERSEDED.value
        or revision.authorization not in {
            Authorization.NOT_REQUESTED.value,
            Authorization.REQUIRED.value,
        }
        or revision.authorization == target
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "revision target is stale")


def _validate_plan_authorization(state: SessionState, plan_id: str) -> None:
    plan = state.plans.get(plan_id)
    if plan is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown plan target")
    divergence = state.divergences.get(plan.divergence_id)
    if (
        plan.state != PlanState.DRAFT.value
        or plan.based_on_intent_revision_id != _active_revision_id(state)
        or divergence is None
        or divergence.state != DivergenceState.PLANNED.value
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "plan target is stale")


def _active_revision_id(state: SessionState) -> str | None:
    if state.active_intent_id is None:
        return None
    intent = state.intents.get(state.active_intent_id)
    return intent.active_revision_id if intent is not None else None


def _serialize_events(
    application: Application,
    session_id: str,
    selected: Sequence[EventEnvelope],
    after_sequence: int,
    all_retained: Sequence[EventEnvelope],
    hub: ProjectionHub | None = None,
) -> list[dict[str, Any]]:
    if not selected:
        return []

    # Check canonical ProjectionHub history first when available
    hub_history: dict[int, dict[str, Any]] = {}
    if hub is not None:
        session_proj = hub._sessions.get(session_id)
        if session_proj is not None:
            hub_history = {msg["sequence"]: msg for msg in session_proj.history}

    # If all selected events are retained in hub history, return them directly
    if all(event.sequence in hub_history for event in selected):
        return [deepcopy(hub_history[event.sequence]) for event in selected]

    # Otherwise, raw events must be replayed from sequence 1.
    # If the retained journal slice no longer starts at sequence 1, history cannot be replayed.
    if not all_retained or all_retained[0].sequence != 1:
        raise HTTPException(
            status.HTTP_410_GONE, "requested event history has expired"
        )

    prefix_events = [e for e in all_retained if e.sequence <= after_sequence]
    if prefix_events:
        try:
            prev_state = application.replay(prefix_events)
            prev_proj = project_state(prev_state)
        except Exception as exc:
            raise HTTPException(
                status.HTTP_410_GONE, "requested event history has expired"
            ) from exc
    else:
        prev_proj = {
            "intent": None,
            **{
                name: []
                for name in (
                    "operations",
                    "effects",
                    "evidence",
                    "claims",
                    "divergences",
                    "plans",
                    "speech",
                )
            },
            "metrics": {},
        }

    results: list[dict[str, Any]] = []
    current_events = list(prefix_events)
    for event in selected:
        if event.sequence in hub_history:
            results.append(deepcopy(hub_history[event.sequence]))
            current_events.append(event)
            try:
                curr_state = application.replay(current_events)
                prev_proj = project_state(curr_state)
            except Exception:
                pass
        else:
            current_events.append(event)
            try:
                curr_state = application.replay(current_events)
            except Exception as exc:
                raise HTTPException(
                    status.HTTP_410_GONE, "requested event history has expired"
                ) from exc
            curr_proj = project_state(curr_state)
            results.append(event_message(event, prev_proj, curr_proj))
            prev_proj = curr_proj

    return results


def _acceptance(event: EventEnvelope) -> dict[str, Any]:
    return {"event_id": event.event_id, "sequence": event.sequence}


def _fingerprint(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(encoded.encode("utf-8")).hexdigest()


def _stable_id(*parts: str) -> str:
    digest = sha256(json.dumps(parts, separators=(",", ":")).encode("utf-8")).hexdigest()
    return f"http-{digest}"


def _session_ws_url(base: str, session_id: str) -> str:
    return f"{base.rstrip('/')}/sessions/{session_id}/stream"


__all__ = [
    "AuthorizationRequest",
    "FaultRequest",
    "InputRequest",
    "ResetRequest",
    "SessionCreateRequest",
    "SpeechCancelRequest",
    "create_http_app",
]
