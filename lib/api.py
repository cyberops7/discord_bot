import logging
from pathlib import Path

import uvicorn
from discord import ClientUser
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from starlette.datastructures import State as StarletteState

from lib.bot import DiscordBot

logger: logging.Logger = logging.getLogger(__name__)


# Custom subclass of Starlette/FastAPI State
class AppState(StarletteState):
    """Custom state object for FastAPI.  This is needed to keep type checkers happy."""

    bot: DiscordBot

    def __init__(self, bot: DiscordBot | None) -> None:
        super().__init__()
        self.bot: DiscordBot | None = bot


app: FastAPI = FastAPI()  # Create the FastAPI app
app.state = AppState(bot=None)


async def start_fastapi_server(bot: DiscordBot, port: int = 8080) -> None:
    """
    Start the FastAPI server using asyncio and provide the bot instance
    to the API
    """
    # Store the bot instance in FastAPI's state object
    app.state.bot = bot

    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_config=None)  # noqa: S104
    server = uvicorn.Server(config)
    await server.serve()


# Explicit favicon.ico route to serve the favicon
@app.get("/favicon.ico")
async def favicon() -> FileResponse:
    favicon_path = Path("static") / "favicon.ico"
    return FileResponse(favicon_path)


class HealthCheckResponse(BaseModel):
    status: str
    message: str


@app.get("/healthcheck")
async def healthcheck(request: Request) -> JSONResponse:
    """
    Healthcheck endpoint that uses the Discord bot instance to check readiness.
    """
    bot = request.app.state.bot
    if bot.is_ready():
        return JSONResponse(
            status_code=200,
            content=HealthCheckResponse(
                status="ok", message="Bot is running and ready"
            ).model_dump(),
        )
    return JSONResponse(
        status_code=503,
        content=HealthCheckResponse(
            status="not_ready", message="Bot is not ready"
        ).model_dump(),
    )


class StatusResponse(BaseModel):
    latency: float
    is_ready: bool
    user: str


@app.get("/status")
async def status(request: Request) -> StatusResponse:
    bot = request.app.state.bot
    latency: float = bot.latency
    is_ready: bool = bot.is_ready()
    user: str = str(bot.user) if isinstance(bot.user, ClientUser) else "Unknown"
    return StatusResponse(
        latency=latency,
        is_ready=is_ready,
        user=user,
    )
