from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.auth.routes import groups_router, router as auth_router
from app.checkins.routes import router as goals_router
from app.config import settings
from app.db import init_db
from app.points.routes import router as points_router

# Built from this file's location, so it works whatever the working directory is.
STATIC_DIR = Path(__file__).parent / "app" / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Accountability Tracker", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(groups_router)
app.include_router(goals_router)
app.include_router(points_router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def index():
    """The single-page frontend; it calls the API above with relative URLs."""
    return FileResponse(STATIC_DIR / "index.html")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
