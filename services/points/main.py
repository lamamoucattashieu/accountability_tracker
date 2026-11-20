import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.db import init_db
from app.points import group_directory
from app.points.internal_routes import router as internal_router
from app.points.routes import router as points_router
from app.shared.database import DatabaseUnavailable
from app.shared.internal_api import add_cors

SERVICE_NAME = "points"

# INFO, so startup lines such as "migration 001_init applied" reach stdout.
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.check_secrets()
    init_db()
    group_directory.set_directory(group_directory.HttpGroupDirectory(
        settings.checkins_url, settings.checkins_timeout_s, settings.internal_api_key,
    ))
    yield


app = FastAPI(title="Points & Forfeits", lifespan=lifespan)
app.include_router(points_router)
app.include_router(internal_router)
add_cors(app)


@app.exception_handler(DatabaseUnavailable)
def database_unavailable(request: Request, exc: DatabaseUnavailable):
    """The database didn't answer even after retrying: a clear 503, not a stack trace."""
    return JSONResponse(status_code=503, content={"detail": "the database is starting up, try again shortly"},
                        headers={"Retry-After": "5"})


@app.get("/health")
def health():
    """Minimal for Phase 1; the full database check and version come in Phase 2."""
    return {"status": "ok", "service": SERVICE_NAME}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
