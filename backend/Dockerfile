FROM python:3.14-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy lockfile first to leverage Docker layer caching
# and ensure we use --frozen (reproducible builds)
COPY pyproject.toml uv.lock .python-version ./

# Install dependencies without building the project yet
# (app code doesn't exist yet)
RUN uv sync --frozen --no-install-project

# Now copy the app code
COPY . .

# Use explicit venv path so bind mount doesn't hide it
ENV UV_PROJECT_ENVIRONMENT=/opt/venv

# Install the project itself
RUN uv sync --frozen

# Run migrations and start the server
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000"]
