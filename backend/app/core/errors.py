"""RFC 7807 problem+json errors (SDD §7)."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

PROBLEM_JSON = "application/problem+json"


class Problem(BaseModel):
    """RFC 7807 problem details body, as returned by `problem_error_handler`."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None


def problem_response(description: str) -> dict[str, Any]:
    """OpenAPI `responses` entry documenting an application/problem+json error."""
    return {
        "description": description,
        "content": {PROBLEM_JSON: {"schema": Problem.model_json_schema()}},
    }


class ProblemError(Exception):
    """Raise from a route or dependency to return an RFC 7807 response."""

    def __init__(
        self,
        status: int,
        title: str,
        detail: str | None = None,
        *,
        headers: dict[str, str] | None = None,
        extra: dict[str, object] | None = None,
    ) -> None:
        super().__init__(title)
        self.status = status
        self.title = title
        self.detail = detail
        self.headers = headers
        self.extra = extra or {}


async def problem_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ProblemError)
    body: dict[str, object] = {"type": "about:blank", "title": exc.title, "status": exc.status}
    if exc.detail is not None:
        body["detail"] = exc.detail
    body.update(exc.extra)
    return JSONResponse(body, status_code=exc.status, headers=exc.headers, media_type=PROBLEM_JSON)
