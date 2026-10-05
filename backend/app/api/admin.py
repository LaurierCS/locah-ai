"""Admin routes — bearer-token protected, for CI/cron and manual ops (SDD §7)."""

import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.core.errors import ProblemError, problem_response
from app.ingest.jobs import CrawlAlreadyRunning, start_crawl_job

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

_bearer = HTTPBearer(auto_error=False)


def require_admin(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> None:
    """Fail closed: an unset ADMIN_TOKEN rejects every request."""
    expected = settings.admin_token
    if (
        not expected
        or credentials is None
        or not secrets.compare_digest(credentials.credentials.encode(), expected.encode())
    ):
        raise ProblemError(
            401,
            "Unauthorized",
            "A valid admin bearer token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.post(
    "/crawl",
    status_code=202,
    dependencies=[Depends(require_admin)],
    responses={
        401: problem_response("Missing or invalid admin bearer token (or ADMIN_TOKEN unset)."),
        409: problem_response("A crawl is already running; its status is in the `job` member."),
    },
)
async def trigger_crawl() -> dict[str, Any]:
    """Start the ingest pipeline in the background and return the job's status."""
    try:
        return start_crawl_job().to_dict()
    except CrawlAlreadyRunning as exc:
        raise ProblemError(
            409,
            "Crawl already running",
            "An ingest job is already in progress.",
            extra={"job": exc.job.to_dict()},
        ) from exc
