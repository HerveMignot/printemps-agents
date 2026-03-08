FROM python:3.13-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy project files (build context is repo root)
COPY pyproject.toml uv.lock ./
COPY main.py ./
COPY lbc/ ./lbc/

# Install dependencies
RUN uv sync --frozen --no-dev

# Run the LBC agent
CMD ["uv", "run", "python", "main.py"]
