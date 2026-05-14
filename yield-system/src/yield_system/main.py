"""FastAPI app — four experiment routers, static site, startup seeding."""
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import stripe
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from yield_system.config import settings
from yield_system.db import connect, init_schema


def _sanctions_empty() -> bool:
    with connect() as c:
        return int(c.execute("SELECT COUNT(*) AS n FROM sanctions_entries").fetchone()["n"]) == 0


def _run_sanctions_ingest() -> None:
    from yield_system.ingest.sanctions_hmt import ingest as ingest_hmt
    from yield_system.ingest.sanctions_ofac import ingest as ingest_ofac

    try:
        added = ingest_ofac()
        print(f"ingest:ofac added={added}", flush=True)
    except Exception as e:
        print(f"ingest:ofac error={e}", flush=True)
    try:
        added = ingest_hmt()
        print(f"ingest:hmt added={added}", flush=True)
    except Exception as e:
        print(f"ingest:hmt error={e}", flush=True)


def _daily_refresh_loop() -> None:
    while True:
        time.sleep(86400)
        _run_sanctions_ingest()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    if _sanctions_empty():
        threading.Thread(target=_run_sanctions_ingest, daemon=True).start()
    threading.Thread(target=_daily_refresh_loop, daemon=True).start()
    yield


def build_app() -> FastAPI:
    init_schema()
    from yield_system import signup, stripe_billing
    from yield_system.experiments import email_score, postcode, sanctions, webhook_q

    s = settings()
    if s.stripe_secret_key:
        stripe.api_key = s.stripe_secret_key
    stripe_billing.refresh_price_map()

    postcode.ensure_table()

    app = FastAPI(title="yield-system", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(signup.router)
    app.include_router(stripe_billing.router)
    app.include_router(postcode.router)
    app.include_router(email_score.router)
    app.include_router(sanctions.router)
    app.include_router(webhook_q.router)

    site_dir = Path(__file__).parent.parent.parent / "site"
    if site_dir.exists():
        app.mount("/", StaticFiles(directory=str(site_dir), html=True), name="site")

    return app


app = build_app()
