import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse

from app.api.auth import auth_router, users_router
from app.api.devices import devices_router
from app.api.matches import matches_router
from app.api.notifications import notifications_router
from app.api.recovery import recovery_router
from app.api.reports import reports_router
from app.core.config import settings
from app.db.database import get_db


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    dispatcher_task: asyncio.Task[None] | None = None
    stop_event: asyncio.Event | None = None

    if settings.RATE_LIMIT_ENABLED:
        from app.core.redis import init_redis_pool

        init_redis_pool()

    if settings.PUSH_DISPATCHER_ENABLED:
        from app.services.push_dispatcher import PushDispatcher

        stop_event = asyncio.Event()
        dispatcher = PushDispatcher()
        dispatcher_task = asyncio.create_task(
            dispatcher.run_loop(stop_event=stop_event)
        )

    try:
        yield
    finally:
        if stop_event is not None and dispatcher_task is not None:
            stop_event.set()
            try:
                await asyncio.wait_for(dispatcher_task, timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                dispatcher_task.cancel()

        if settings.RATE_LIMIT_ENABLED:
            from app.core.redis import close_redis_pool

            await close_redis_pool()


app = FastAPI(
    title="Community Missing Item & Asset Tracker",
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix=f"{settings.API_V1_STR}/auth", tags=["auth"])
app.include_router(users_router, prefix=f"{settings.API_V1_STR}/users", tags=["users"])
app.include_router(
    reports_router, prefix=f"{settings.API_V1_STR}/reports", tags=["reports"]
)
app.include_router(
    recovery_router,
    prefix=f"{settings.API_V1_STR}/recovery-requests",
    tags=["recovery-requests"],
)
app.include_router(matches_router, prefix=f"{settings.API_V1_STR}", tags=["matches"])
app.include_router(
    notifications_router,
    prefix=f"{settings.API_V1_STR}/notifications",
    tags=["notifications"],
)
app.include_router(
    devices_router,
    prefix=f"{settings.API_V1_STR}/devices",
    tags=["devices"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    print(f"GLOBAL EXCEPTION CAUGHT: {exc}")
    import traceback

    traceback.print_exc()

    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        # Check database connectivity
        await db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "error"

    redis_status = "disabled"
    if settings.RATE_LIMIT_ENABLED:
        from app.core.redis import check_redis_health

        redis_ok = await check_redis_health()
        redis_status = "ok" if redis_ok else "error"

    overall_status = (
        "ok"
        if db_status == "ok" and (redis_status in ("ok", "disabled"))
        else "degraded"
    )
    return {
        "status": overall_status,
        "database": db_status,
        "redis": redis_status,
    }
