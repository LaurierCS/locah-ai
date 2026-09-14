"""LOCAH.ai API entrypoint."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings

app = FastAPI(
    title="LOCAH.ai",
    description="An assistant over Wilfrid Laurier University's public information.",
    version="0.1.0",
)

# CORS: allow the frontend and localhost development to access the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # Next.js dev
        "http://127.0.0.1:3000",
        "http://localhost",  # Docker internal
        "http://frontend:3000",  # Docker Compose service
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/v1/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "model": settings.anthropic_model,
        # Populated once ingest (S1) writes crawl metadata. Keys match SDD §7.
        "last_crawl_at": None,
        "active_documents": None,
    }
