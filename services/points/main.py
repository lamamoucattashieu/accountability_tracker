from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app.config import settings
from app.db import init_db
from app.points.routes import router as points_router

SERVICE_NAME = "points"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.check_secrets()
    init_db()
    yield


app = FastAPI(title="Points & Forfeits", lifespan=lifespan)
app.include_router(points_router)


@app.get("/health")
def health():
    """Minimal for Phase 1; the full database check and version come in Phase 2."""
    return {"status": "ok", "service": SERVICE_NAME}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
