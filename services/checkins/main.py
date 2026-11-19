from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app.auth.routes import groups_router, router as auth_router
from app.checkins.routes import router as goals_router
from app.config import settings
from app.db import init_db

SERVICE_NAME = "checkins"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.check_secrets()
    init_db()
    yield


app = FastAPI(title="Goals & Check-ins", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(groups_router)
app.include_router(goals_router)


@app.get("/health")
def health():
    """Minimal for Phase 1; the full database check and version come in Phase 2."""
    return {"status": "ok", "service": SERVICE_NAME}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
