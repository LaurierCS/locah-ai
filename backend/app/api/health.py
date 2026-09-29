from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db

health_router = APIRouter()


@health_router.get("/health")
async def health(response: Response, db: Session = Depends(get_db)) -> dict[str, object]:
    """
    Liveness check and Knowledge Base freshness indicator.
    Returns 200 OK if DB is reachable, 503 Service Unavailable if not.
    """
    try:
        # 1. KB Freshness: Last time any document was fetched
        # Use text() for raw SQL as we are maintaining a lightweight health check
        res_last_crawl = db.execute(text("SELECT MAX(fetched_at) FROM documents")).scalar()

        # 2. KB Volume: Count of active document chunks
        res_active_docs = db.execute(
            text("SELECT COUNT(*) FROM documents WHERE is_active = true")
        ).scalar()

        return {
            "status": "ok",
            "last_crawl_at": res_last_crawl,
            "active_documents": res_active_docs or 0,
        }

    except Exception as e:
        # If database is unreachable or query fails, return 503 degraded
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "degraded", "error": str(e)}
