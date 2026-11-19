from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app.config import settings
from app.db import init_db
from app.points import group_directory
from app.points.internal_routes import router as internal_router
from app.points.routes import router as points_router
from app.shared.internal_api import add_cors

SERVICE_NAME = "points"


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


@app.get("/health")
def health():
    """Minimal for Phase 1; the full database check and version come in Phase 2."""
    return {"status": "ok", "service": SERVICE_NAME}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
