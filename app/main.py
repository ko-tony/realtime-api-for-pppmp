from fastapi import FastAPI, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.environment import v1_router
from app.api.finance import v1_router as finance_router
from app.core.database import DatabaseSession
from app.api.creative_relay import (
    PATH as CREATIVE_RELAY_PATH,
    BETA_PATH as CREATIVE_RELAY_BETA_PATH,
    load_relay_settings,
    router as creative_relay_router,
)
from app.middleware.path_cors import PathCORSMiddleware

app = FastAPI(
    title="Realtime API for PPPMP ads",
    description="Public supplementary data API for PPPMP ads.",
    version="1.0.0",
)

app.state.creative_relay_settings = load_relay_settings()
app.state.creative_relay_beta_settings = load_relay_settings("beta")
app.add_middleware(
    PathCORSMiddleware,
    policies={
        path: (settings is not None, settings.origins if settings else ())
        for path, settings in (
            (CREATIVE_RELAY_PATH, app.state.creative_relay_settings),
            (CREATIVE_RELAY_BETA_PATH, app.state.creative_relay_beta_settings),
        )
    },
)
app.include_router(creative_relay_router)


app.include_router(v1_router)
app.include_router(finance_router)


@app.get("/", include_in_schema=False)
def read_root() -> dict[str, str]:
    return {"Hello": "World"}


@app.get("/health", include_in_schema=False)
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready", include_in_schema=False)
def readiness(db: DatabaseSession) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable",
        ) from error
    return {"status": "ready"}
