"""POST /api/v1/admin/crawl — auth, job lifecycle, and failure handling (issue #38).

The pipeline runner is patched, so these tests need no database, network, or model.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Any

import httpx
import pytest
import pytest_asyncio

from app.core.config import settings
from app.ingest import jobs
from app.ingest.pipeline import IngestSummary
from app.main import app

URL = "/api/v1/admin/crawl"
TOKEN = "test-admin-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest_asyncio.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[httpx.AsyncClient]:
    monkeypatch.setattr(settings, "admin_token", TOKEN)
    jobs.reset_jobs()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    jobs.reset_jobs()


def patch_runner(
    monkeypatch: pytest.MonkeyPatch,
    fn: Callable[[], Coroutine[Any, Any, IngestSummary]],
) -> list[int]:
    calls: list[int] = []

    async def runner() -> IngestSummary:
        calls.append(1)
        return await fn()

    monkeypatch.setattr(jobs, "_execute", runner)
    return calls


async def _ok() -> IngestSummary:
    return IngestSummary(pages_fetched=3, chunks_upserted=12, skipped_unchanged=1)


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong"},
        {"Authorization": f"Basic {TOKEN}"},
        {"Authorization": "Bearer "},
        {"Authorization": TOKEN},
    ],
)
async def test_rejects_bad_credentials_without_running_pipeline(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, headers: dict[str, str]
) -> None:
    calls = patch_runner(monkeypatch, _ok)
    resp = await client.post(URL, headers=headers)
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["status"] == 401
    await jobs.wait_for_current_job()
    assert calls == []


@pytest.mark.parametrize("sent", ["", "anything"])
async def test_unset_admin_token_fails_closed(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, sent: str
) -> None:
    monkeypatch.setattr(settings, "admin_token", "")
    calls = patch_runner(monkeypatch, _ok)
    resp = await client.post(URL, headers={"Authorization": f"Bearer {sent}"})
    assert resp.status_code == 401
    assert calls == []


async def test_valid_token_returns_202_and_runs_pipeline(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = patch_runner(monkeypatch, _ok)
    resp = await client.post(URL, headers=AUTH)
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "running"
    assert body["job_id"]
    assert body["finished_at"] is None

    await jobs.wait_for_current_job()
    assert calls == [1]
    job = jobs._current
    assert job is not None
    assert job.status == "succeeded"
    assert job.finished_at is not None
    assert job.summary == {
        "pages_fetched": 3,
        "chunks_upserted": 12,
        "skipped_unchanged": 1,
        "extract_skipped": 0,
        "errors": 0,
    }


async def test_second_request_while_running_returns_409_then_allows_new_job(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = asyncio.Event()

    async def slow() -> IngestSummary:
        await gate.wait()
        return IngestSummary()

    calls = patch_runner(monkeypatch, slow)
    first = await client.post(URL, headers=AUTH)
    assert first.status_code == 202

    second = await client.post(URL, headers=AUTH)
    assert second.status_code == 409
    assert second.headers["content-type"].startswith("application/problem+json")
    body = second.json()
    assert body["status"] == 409
    assert body["job"]["job_id"] == first.json()["job_id"]
    assert body["job"]["status"] == "running"

    gate.set()
    await jobs.wait_for_current_job()
    third = await client.post(URL, headers=AUTH)
    assert third.status_code == 202
    assert third.json()["job_id"] != first.json()["job_id"]
    await jobs.wait_for_current_job()
    assert len(calls) == 2


async def test_pipeline_failure_marks_job_failed_without_leaking_details(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom() -> IngestSummary:
        raise RuntimeError("postgres://secret-host/locah exploded")

    patch_runner(monkeypatch, boom)
    assert (await client.post(URL, headers=AUTH)).status_code == 202
    await jobs.wait_for_current_job()

    job = jobs._current
    assert job is not None
    assert job.status == "failed"
    assert job.summary is None
    assert job.error is not None
    assert "secret-host" not in job.error

    patch_runner(monkeypatch, _ok)
    assert (await client.post(URL, headers=AUTH)).status_code == 202
    await jobs.wait_for_current_job()


async def test_openapi_documents_problem_json_errors(client: httpx.AsyncClient) -> None:
    op = (await client.get("/openapi.json")).json()["paths"][URL]["post"]
    assert "202" in op["responses"]
    for code in ("401", "409"):
        assert "application/problem+json" in op["responses"][code]["content"]
