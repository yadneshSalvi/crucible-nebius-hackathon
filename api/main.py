from __future__ import annotations

import asyncio
import secrets
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import Settings
from .exporting import export_bundle, report
from .orchestrator import ACTIVE, Orchestrator
from .store import Conflict, Store


class CreateFolio(BaseModel):
    model_config = ConfigDict(extra="forbid")
    adapter_id: Literal["occupancy", "synthetic"]
    title: str | None = Field(default=None, min_length=3, max_length=120)
    claim: str | None = Field(default=None, min_length=20, max_length=800)


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=128)
    claim: str | None = Field(default=None, min_length=20, max_length=800)
    title: str | None = Field(default=None, min_length=3, max_length=120)
    practical_delta: float | None = Field(default=None, ge=0, le=0.10)
    reviewer_name: str | None = Field(default=None, max_length=100)
    review_note: str | None = Field(default=None, max_length=2000)
    reason: str | None = Field(default=None, max_length=2000)
    condition_id: str | None = Field(default=None, max_length=100)


def create_app(settings: Settings | None = None, seed: bool = True) -> FastAPI:
    cfg = settings or Settings.read()
    store = Store(cfg.root)
    runner = Orchestrator(cfg, store)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if seed:
            await runner.startup()
        yield
        await runner.shutdown()

    app = FastAPI(title="Crucible trusted local control plane", version="0.1.0", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    app.state.store, app.state.runner = store, runner
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    @app.middleware("http")
    async def guards(request: Request, call_next):
        origin = request.headers.get("origin")
        allowed = {"http://127.0.0.1:4201", "http://localhost:4201", "http://127.0.0.1:4202", "http://localhost:4202"}
        if origin and origin not in allowed:
            return JSONResponse({"error": {"code": "origin_rejected", "message": "This local workbench accepts its own browser origin only.", "recoverable": False}}, status_code=403)
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            supplied = request.headers.get("x-crucible-session", "")
            if not secrets.compare_digest(supplied, store.session_token):
                return JSONResponse({"error": {"code": "session_required", "message": "Refresh the local workbench session before making changes.", "recoverable": True}}, status_code=403)
            if "application/json" not in request.headers.get("content-type", ""):
                return JSONResponse({"error": {"code": "json_required", "message": "Actions require a JSON body.", "recoverable": True}}, status_code=415)
            try:
                size = int(request.headers.get("content-length", "0"))
            except ValueError:
                size = 1_000_000
            if size > 32768:
                return JSONResponse({"error": {"code": "body_too_large", "message": "Action payload exceeds the 32 KiB bound.", "recoverable": True}}, status_code=413)
            body = await request.body()
            if len(body) > 32768:
                return JSONResponse({"error": {"code": "body_too_large", "message": "Action payload exceeds the 32 KiB bound.", "recoverable": True}}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(Conflict)
    async def conflict_handler(request: Request, exc: Conflict):
        return JSONResponse({"error": {"code": exc.code, "message": exc.message, "recoverable": True}}, status_code=409)

    @app.exception_handler(KeyError)
    async def missing_handler(request: Request, exc: KeyError):
        return JSONResponse({"error": {"code": "not_found", "message": "This folio or immutable artifact does not exist.", "recoverable": True}}, status_code=404)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        return JSONResponse({"error": {"code": "invalid_input", "message": "Input did not match the supported typed action. Check required fields, lengths and numerical bounds.", "recoverable": True, "fields": [".".join(str(x) for x in e["loc"]) for e in exc.errors()]}}, status_code=422)

    @app.get("/api/session")
    async def session():
        return {"token": store.session_token, "mode": "local_operator"}

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "product": "Crucible", "version": "0.1.0", "provider": cfg.public(), "adapters": ["occupancy", "synthetic"], "mode": "trusted_local", "ports": {"ui": 4201, "api": 4202}, "scope": "Authored tabular comparisons. Arbitrary paper/repository imports are not supported; original paper protocol matching and external scientific review are pending."}

    @app.get("/api/folios")
    async def folios():
        return {"folios": [{k: f.get(k) for k in ("id", "adapter_id", "title", "claim", "case_kind", "created_at", "updated_at", "revision", "stage", "status", "conclusion", "run", "reproduction_accepted")} for f in store.list()]}

    @app.post("/api/folios", status_code=201)
    async def create_folio(body: CreateFolio):
        return await runner.create(**body.model_dump())

    @app.get("/api/folios/{folio_id}")
    async def folio(folio_id: str):
        return store.get(folio_id)

    @app.get("/api/folios/{folio_id}/events")
    async def events(folio_id: str, after: int = 0):
        store.get(folio_id)
        return store.events(folio_id, max(0, after))

    @app.post("/api/folios/{folio_id}/actions/{action}")
    async def act(folio_id: str, action: str, body: Action):
        doc = await runner.action(folio_id, action, body.model_dump(exclude_none=True))
        return JSONResponse(doc, status_code=202 if doc.get("run") and doc["run"]["status"] in ACTIVE else 200)

    @app.get("/api/artifacts/{sha}")
    async def artifact(sha: str):
        path, meta = store.get_artifact(sha)
        return FileResponse(path, media_type=meta["media_type"], filename=meta["name"])

    @app.get("/api/folios/{folio_id}/report", response_class=HTMLResponse)
    async def html_report(folio_id: str):
        response = HTMLResponse(report(store.get(folio_id)))
        response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"
        return response

    @app.get("/api/folios/{folio_id}/export")
    async def export(folio_id: str):
        content, filename = await asyncio.to_thread(export_bundle, store, store.get(folio_id))
        return Response(content, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    return app


app = create_app()
