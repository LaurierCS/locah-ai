"""LOCAH.ai API entrypoint."""

from fastapi import FastAPI

from app.core.config import settings

app = FastAPI(
    title="LOCAH.ai",
    description="An assistant over Wilfrid Laurier University's public information.",
    version="0.1.0",
)


@app.get("/api/v1/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "model": settings.anthropic_model,
        # TODO(platform-pod): report last_crawl_at and active_documents from the DB.
    }
