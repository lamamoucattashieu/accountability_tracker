from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app.auth.routes import groups_router, router as auth_router
from app.checkins import points_client
from app.checkins.internal_routes import router as internal_router
from app.checkins.routes import router as goals_router
from app.config import settings
from app.db import init_db
from app.shared.internal_api import add_cors

SERVICE_NAME = "checkins"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.check_secrets()
    init_db()
    points_client.set_client(points_client.HttpPointsClient(
        settings.points_url, settings.points_timeout_s, settings.internal_api_key,
    ))
    yield


app = FastAPI(title="Goals & Check-ins", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(groups_router)
app.include_router(goals_router)
app.include_router(internal_router)
add_cors(app)


@app.get("/health")
def health():
    """Minimal for Phase 1; the full database check and version come in Phase 2."""
    return {"status": "ok", "service": SERVICE_NAME}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
