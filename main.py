from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app.auth.routes import groups_router, router as auth_router
from app.checkins.routes import router as goals_router
from app.config import settings
from app.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Accountability Tracker", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(groups_router)
app.include_router(goals_router)


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
