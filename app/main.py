from typing import Any

from fastapi import Depends, FastAPI, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse

from app.api.auth import auth_router, users_router
from app.api.reports import reports_router
from app.core.config import settings
from app.db.database import get_db

app = FastAPI(title="Community Missing Item & Asset Tracker")

app.include_router(auth_router, prefix=f"{settings.API_V1_STR}/auth", tags=["auth"])
app.include_router(users_router, prefix=f"{settings.API_V1_STR}/users", tags=["users"])
app.include_router(
    reports_router, prefix=f"{settings.API_V1_STR}/reports", tags=["reports"]
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    print(f"GLOBAL EXCEPTION CAUGHT: {exc}")
    import traceback

    traceback.print_exc()

    return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        # Check database connectivity
        await db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "error"

    return {"status": "ok", "database": db_status}
