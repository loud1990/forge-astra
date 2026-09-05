FROM python:3.13-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.12 /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.13-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 astra && useradd --uid 10001 --gid astra --create-home astra \
    && mkdir -p /data /output && chown astra:astra /data /output
COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    ASTRA_DATA_DIR=/data \
    ASTRA_OUTPUT_DIR=/output
USER astra
WORKDIR /home/astra
VOLUME ["/data", "/output"]
HEALTHCHECK --interval=5m --timeout=15s --start-period=15m --retries=3 \
    CMD ["forge-astra", "health"]
ENTRYPOINT ["forge-astra"]
CMD ["watch"]

