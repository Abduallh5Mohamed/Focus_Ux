"""FastAPI application factory and HTTP routes.

Wire shapes follow ``product/apps/web/src/lib/api/types.ts`` (read-only) and
docs/02_CONTRACTS.md exactly. Protected media never accepts a token in the URL.
"""
from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from services.worker.interfaces import JobDirectoryLayout
from services.worker.worker import SingleWorker

from .config import Settings
from .db import SqliteRepository
from .dispatcher import Dispatcher
from .errors import ApiError, unauthorized
from .interfaces import (
    ExtractionRunner,
    FaceCandidateProvider,
    UnavailableCandidateProvider,
    UnavailableExtractionRunner,
)
from .lock import DispatcherLock
from .schemas import CreateJobRequest
from .service import ApiService
from .storage import Storage

logger = logging.getLogger("focus_api")


def _optional_bearer(request: Request) -> Optional[str]:
    header = request.headers.get("authorization")
    if header is None:
        return None
    scheme, _, value = header.partition(" ")
    token = value.strip()
    if scheme.lower() != "bearer" or not token:
        raise unauthorized("authorization header must use the Bearer scheme")
    return token


def _required_session(request: Request, service: ApiService) -> str:
    return service.authenticate(_optional_bearer(request))


def _parse_range(header: str, size: int) -> tuple[int, int]:
    """Parse one ``bytes=`` range. Raises ValueError when unsatisfiable."""
    if size <= 0:
        raise ValueError("range requires a nonempty file")
    if not header.lower().startswith("bytes="):
        raise ValueError("unsupported range unit")
    spec = header[6:].strip()
    # int() also accepts signs, underscores, whitespace and Unicode digits,
    # none of which belong in HTTP byte positions. Reject multiple ranges too.
    match = re.fullmatch(r"([0-9]*)-([0-9]*)", spec)
    if match is None:
        raise ValueError("malformed or multiple ranges")
    start_raw, end_raw = match.groups()
    if start_raw == "":
        if end_raw == "":
            raise ValueError("malformed range")
        suffix = int(end_raw)
        if suffix <= 0:
            raise ValueError("malformed range")
        start = max(0, size - suffix)
        end = size - 1
    else:
        start = int(start_raw)
        end = int(end_raw) if end_raw else size - 1
        if start > end:
            raise ValueError("malformed range")
    if start >= size:
        raise ValueError("range starts past the end")
    return start, min(end, size - 1)


def _file_response(request: Request, path: Path, media_type: str) -> Response:
    size = path.stat().st_size
    range_headers = request.headers.getlist("range")
    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, no-store",
    }
    if range_headers:
        try:
            start, end = _parse_range(",".join(range_headers), size)
        except (ValueError, TypeError):
            return Response(
                status_code=416,
                headers={**headers, "Content-Range": f"bytes */{size}"},
            )
        length = end - start + 1
        with open(path, "rb") as handle:
            handle.seek(start)
            data = handle.read(length)
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        headers["Content-Length"] = str(len(data))
        return Response(content=data, status_code=206, media_type=media_type, headers=headers)
    data = path.read_bytes()
    headers["Content-Length"] = str(len(data))
    return Response(content=data, status_code=200, media_type=media_type, headers=headers)


def create_app(
    *,
    settings: Optional[Settings] = None,
    candidate_provider: Optional[FaceCandidateProvider] = None,
    extraction_runner: Optional[ExtractionRunner] = None,
    transcriber=None,
    start_dispatcher: bool = True,
    dispatcher_lock: Optional[DispatcherLock] = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    storage = Storage(settings)
    repo = SqliteRepository(settings.db_file)
    provider = candidate_provider or UnavailableCandidateProvider()
    runner = extraction_runner or UnavailableExtractionRunner()
    worker = SingleWorker(
        repo=repo,
        targeting=runner,
        layout=JobDirectoryLayout(job_dir_root=str(settings.jobs_dir)),
        transcriber=transcriber,
        max_upload_mb=settings.max_upload_mb,
    )
    dispatcher = Dispatcher(
        settings=settings,
        storage=storage,
        repo=repo,
        worker=worker,
        candidate_provider=provider,
        extraction_runner=runner,
        lock=dispatcher_lock,
    )
    service = ApiService(
        settings=settings, storage=storage, repo=repo, dispatcher=dispatcher
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        storage.ensure()
        app.state.dispatcher_started = (
            dispatcher.start() if start_dispatcher else False
        )
        try:
            yield
        finally:
            dispatcher.stop()
            repo.close()

    app = FastAPI(
        title="FOCUS local API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.storage = storage
    app.state.repo = repo
    app.state.worker = worker
    app.state.dispatcher = dispatcher
    app.state.service = service
    app.state.candidate_provider = provider
    app.state.extraction_runner = runner

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.ui_origins),
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept", "Range"],
        expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
        allow_credentials=False,
        max_age=600,
    )

    # -- error rendering (unified docs/02 shape) ---------------------------
    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError):
        return JSONResponse(
            exc.payload(), status_code=exc.status_code, headers=exc.headers or None
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError):
        return JSONResponse(
            {
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "request body or parameters are invalid",
                    "retryable": False,
                }
            },
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            code = "NOT_FOUND"
            message = "resource not found"
        elif exc.status_code == 405:
            code = "INVALID_REQUEST"
            message = "method not allowed"
        else:
            code = "SERVER_ERROR"
            message = "request could not be completed"
        return JSONResponse(
            {"error": {"code": code, "message": message, "retryable": False}},
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception):
        logger.exception("unhandled API error")
        return JSONResponse(
            {
                "error": {
                    "code": "SERVER_ERROR",
                    "message": "internal server error",
                    "retryable": True,
                }
            },
            status_code=500,
        )

    # -- routes ------------------------------------------------------------
    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "dispatcher": bool(dispatcher.lock_acquired)}

    @app.post("/videos", status_code=201)
    def post_video(request: Request, file: UploadFile = File(...)):
        token = _optional_bearer(request)
        body, _new_token = service.upload(
            stream=file.file, content_type=file.content_type, token=token
        )
        return JSONResponse(body, status_code=201)

    @app.get("/videos/{video_id}/faces")
    def get_faces(video_id: str, request: Request):
        session_id = _required_session(request, service)
        return service.faces_response(video_id, session_id)

    @app.get("/videos/{video_id}/original")
    def get_original(video_id: str, request: Request):
        session_id = _required_session(request, service)
        path, media_type = service.original_file(video_id, session_id)
        return _file_response(request, path, media_type)

    @app.get("/videos/{video_id}/faces/{face_id}/thumbnail")
    def get_thumbnail(video_id: str, face_id: str, request: Request):
        session_id = _required_session(request, service)
        path, media_type = service.thumbnail_file(video_id, face_id, session_id)
        return _file_response(request, path, media_type)

    @app.post("/jobs", status_code=202)
    def post_job(payload: CreateJobRequest, request: Request):
        session_id = _required_session(request, service)
        job_id, _created = service.create_job(
            video_id=payload.video_id,
            face_id=payload.face_id,
            client_request_id=payload.client_request_id,
            session_id=session_id,
        )
        # CreateJobResponse is exactly {job_id}; status 202 either way.
        return JSONResponse({"job_id": job_id}, status_code=202)

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str, request: Request):
        session_id = _required_session(request, service)
        return service.job_state(job_id, session_id)

    @app.get("/jobs/{job_id}/audio")
    def get_audio(job_id: str, request: Request):
        session_id = _required_session(request, service)
        path, media_type = service.audio_file(job_id, session_id)
        return _file_response(request, path, media_type)

    @app.get("/jobs/{job_id}/transcript")
    def get_transcript(job_id: str, request: Request):
        session_id = _required_session(request, service)
        return service.transcript_response(job_id, session_id)

    @app.delete("/videos/{video_id}", status_code=202)
    def delete_video(video_id: str, request: Request):
        session_id = _required_session(request, service)
        body = service.delete_video(video_id, session_id)
        return JSONResponse(body, status_code=202)

    return app
