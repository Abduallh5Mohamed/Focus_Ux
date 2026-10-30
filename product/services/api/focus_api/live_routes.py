"""HTTP surface of the experimental live mode. All routes use the session bearer."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from .errors import ApiError
from .live import LiveManager
from .live_stream import StreamHub


class TargetBody(BaseModel):
    face_id: str


class BboxBody(BaseModel):
    bbox: list[int] = Field(min_length=4, max_length=4)


class PlaybackChunk(BaseModel):
    seq: int
    capture_wall_ms: float
    audible_wall_ms: float | None = None


class PlaybackBody(BaseModel):
    chunks: list[PlaybackChunk] = Field(default_factory=list, max_length=2000)
    underruns: int = 0
    rebuffers: int = 0


def add_live_routes(app: FastAPI, manager: LiveManager, service, optional_bearer,
                    hub: StreamHub | None = None) -> None:
    def owner(request: Request) -> str:
        return service.authenticate(optional_bearer(request))

    @app.get("/live/status")
    def live_status():
        st = manager.settings
        return {
            "enabled": st.live_enabled, "experimental": True, "chunk_ms": st.live_chunk_ms,
            "max_chunks": st.live_max_chunks, "max_queue_depth": st.live_max_queue_depth,
            "stream_enabled": bool(hub and st.live_stream_enabled),
        }

    @app.post("/live/sessions", status_code=201)
    def create_session(request: Request):
        token = optional_bearer(request)
        new_token = None
        if token:
            session_id = service.authenticate(token)
        else:
            new_token, session_id = service.new_session()
        s = manager.create(session_id)
        body = {"live_session_id": s.live_id, "experimental": True,
                "chunk_ms": manager.settings.live_chunk_ms,
                "max_chunks": manager.settings.live_max_chunks}
        if new_token:
            body["session_token"] = new_token
        return JSONResponse(body, status_code=201)

    @app.put("/live/sessions/{live_id}/chunks/{seq}")
    async def put_chunk(live_id: str, seq: int, request: Request,
                        capture_start_ms: int, duration_ms: int):
        who = owner(request)
        limit = manager.settings.live_max_chunk_bytes
        data = bytearray()
        async for part in request.stream():
            data.extend(part)
            if len(data) > limit:
                raise ApiError("LIMIT_EXCEEDED", "chunk is too large", status_code=413)
        return await run_in_threadpool(
            manager.ingest, live_id, who, seq, capture_start_ms, duration_ms, bytes(data)
        )

    @app.get("/live/sessions/{live_id}")
    def get_session(live_id: str, request: Request):
        return manager.view(live_id, owner(request))

    @app.post("/live/sessions/{live_id}/target")
    def post_target(live_id: str, body: TargetBody, request: Request):
        manager.set_target(live_id, owner(request), body.face_id)
        return manager.view(live_id, owner(request))

    @app.get("/live/sessions/{live_id}/chunks/{seq}/audio")
    def get_chunk_audio(live_id: str, seq: int, request: Request):
        from .routes import _file_response
        path = manager.chunk_audio(live_id, owner(request), seq)
        return _file_response(request, path, "audio/wav")

    @app.post("/live/sessions/{live_id}/playback")
    def post_playback(live_id: str, body: PlaybackBody, request: Request):
        manager.set_playback(live_id, owner(request), body.model_dump())
        return {"accepted": True}

    @app.post("/live/sessions/{live_id}/stop")
    def stop_session(live_id: str, request: Request):
        manager.stop(live_id, owner(request))
        return manager.view(live_id, owner(request))

    @app.get("/live/sessions/{live_id}/metrics")
    def get_metrics(live_id: str, request: Request):
        return manager.metrics(live_id, owner(request))

    if hub is None:
        return

    @app.post("/live/stream/sessions", status_code=201)
    def create_stream(request: Request):
        token = optional_bearer(request)
        new_token = None
        if token:
            session_id = service.authenticate(token)
        else:
            new_token, session_id = service.new_session()
        s = hub.create(session_id)
        body = {"live_session_id": s.live_id, "experimental": True, "config": s.config}
        if new_token:
            body["session_token"] = new_token
        return JSONResponse(body, status_code=201)

    @app.post("/live/stream/sessions/{live_id}/in")
    async def stream_in(live_id: str, request: Request):
        who = owner(request)
        data = bytearray()
        async for part in request.stream():
            data.extend(part)
            if len(data) > 4 * 1024 * 1024:
                raise ApiError("LIMIT_EXCEEDED", "stream batch is too large", status_code=413)
        return await run_in_threadpool(hub.ingest, live_id, who, bytes(data))

    @app.get("/live/stream/sessions/{live_id}/out")
    async def stream_out(live_id: str, request: Request, after: int = -1, wait_ms: int = 800):
        who = owner(request)
        body = await run_in_threadpool(hub.out, live_id, who, after, wait_ms / 1000)
        if body is None:
            return Response(status_code=204)
        return Response(body, media_type="application/octet-stream", headers={"Cache-Control": "no-store"})

    @app.get("/live/stream/sessions/{live_id}")
    def stream_view(live_id: str, request: Request):
        return hub.view(live_id, owner(request))

    @app.post("/live/stream/sessions/{live_id}/target")
    def stream_target(live_id: str, body: BboxBody, request: Request):
        return hub.set_target(live_id, owner(request), body.bbox)

    @app.post("/live/stream/sessions/{live_id}/playback")
    def stream_playback(live_id: str, body: PlaybackBody, request: Request):
        hub.set_playback(live_id, owner(request), body.model_dump())
        return {"accepted": True}

    @app.post("/live/stream/sessions/{live_id}/stop")
    def stream_stop(live_id: str, request: Request):
        return hub.stop(live_id, owner(request))

    @app.get("/live/stream/sessions/{live_id}/metrics")
    def stream_metrics(live_id: str, request: Request, quality_delta_db: float | None = None):
        return hub.metrics(live_id, owner(request), quality_delta_db)

    @app.get("/live/stream/sessions/{live_id}/audio")
    def stream_audio(live_id: str, request: Request):
        from .routes import _file_response
        return _file_response(request, hub.wav(live_id, owner(request)), "audio/wav")
