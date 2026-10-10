from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .service import PaperBot

ROOT = Path(__file__).resolve().parent.parent


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    aggressiveness: int | None = Field(None, ge=1, le=10)
    operation_mode: Literal["operate", "close_only"] | None = None
    market_source: Literal["demo", "kraken"] | None = None
    ai_enabled: bool | None = None
    cycle_seconds: int | None = Field(None, ge=30, le=3600)
    max_positions: int | None = Field(None, ge=1, le=8)
    daily_loss_limit_pct: float | None = Field(None, ge=0.5, le=10, allow_inf_nan=False)


class ResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    initial_balance: float = Field(10_000, ge=100, le=1_000_000_000, allow_inf_nan=False)


class NewsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=5, max_length=2000)


def create_app(db_path: str | Path | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application):
        application.state.bot = PaperBot(
            db_path or os.environ.get("BOT_DB_PATH", str(ROOT / ".local" / "paper.sqlite3")),
            initial_source=os.environ.get("BOT_INITIAL_SOURCE", "demo"),
        )
        yield
        await application.state.bot.shutdown()

    application = FastAPI(title="Vector · laboratorio de trading", lifespan=lifespan)

    @application.middleware("http")
    async def local_mutations(request: Request, call_next):
        # Local app, same-origin UI. Never expose this server publicly without authentication.
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            from urllib.parse import urlsplit
            origin = request.headers.get("origin")
            rejected = False
            if origin:
                try:
                    parsed = urlsplit(origin)
                    rejected = (parsed.scheme not in ("http", "https")
                                or parsed.scheme != request.url.scheme
                                or parsed.netloc != request.headers.get("host")
                                or bool(parsed.path or parsed.query or parsed.fragment)
                                or parsed.username is not None)
                except ValueError:
                    rejected = True
            if rejected:
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail": "Origen no permitido."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @application.exception_handler(ValueError)
    async def value_error(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @application.get("/api/health")
    async def health():
        return {"status": "ok", "mode": "paper"}

    @application.get("/api/state")
    async def state(request: Request):
        async with request.app.state.bot.lock:
            return request.app.state.bot.snapshot()

    @application.post("/api/settings")
    async def settings(request: Request, update: SettingsUpdate):
        return await request.app.state.bot.settings(update.model_dump(exclude_none=True))

    @application.post("/api/start")
    async def start(request: Request):
        return await request.app.state.bot.start()

    @application.post("/api/stop")
    async def stop(request: Request):
        return await request.app.state.bot.stop()

    @application.post("/api/cycle")
    async def cycle(request: Request):
        return await request.app.state.bot.cycle()

    @application.post("/api/positions/{identifier}/close")
    async def close(request: Request, identifier: str):
        return await request.app.state.bot.close(identifier)

    @application.post("/api/reset")
    async def reset(request: Request, body: ResetRequest):
        return await request.app.state.bot.reset(body.initial_balance)

    @application.post("/api/news")
    async def news(request: Request, body: NewsRequest):
        if len(body.text.strip()) < 5:
            raise HTTPException(422, "Escribe al menos cinco caracteres de contexto.")
        return await request.app.state.bot.add_news(body.text.strip())

    @application.get("/")
    async def index():
        return FileResponse(ROOT / "web" / "index.html")

    application.mount("/static", StaticFiles(directory=ROOT / "web", check_dir=False), name="static")
    return application


app = create_app()
