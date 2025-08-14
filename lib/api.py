import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from discord import ClientUser, Intents
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


@asynccontextmanager
async def lifespan(api_app: FastAPI) -> AsyncIterator[None]:
    logger.info("Initializing Discord bot...")

    # Initialize the bot with the necessary intents
    intents = Intents.all()
    bot = DiscordBot(command_prefix="!", intents=intents)

    # Retrieve the bot token from environment variables
    logger.info("Retrieving bot token...")
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        msg = "BOT_TOKEN is required to start the bot."
        logger.error(msg)
        raise RuntimeError(msg)

    # Start the bot
    logger.info("Starting Discord bot...")
    # Start the bot asynchronously (in the background) to not block 'app's lifespan
    bot_task = asyncio.create_task(bot.start(bot_token, reconnect=True))

    # Save the bot instance to FastAPI's state
    api_app.state = AppState(bot=bot)

    try:
        # Yield control back to FastAPI to start up the server
        yield

    finally:
        logger.info("Shutting down Discord bot...")

        # Gracefully close the bot
        await bot.close()

        # Ensure the bot task is cleaned up
        await bot_task
        logger.info("Discord bot closed.")


# pyre-ignore[6]: FastAPI expects AbstractAsyncContextManager,
# but we are using the asynccontextmanager decorator (per FastAPI docs)
app: FastAPI = FastAPI(lifespan=lifespan)  # Create the FastAPI app


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
    Health check endpoint that uses the Discord bot instance to check readiness.
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
