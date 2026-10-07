FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 PYTHONPATH=/app
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY corecoder ./corecoder
RUN python -m pip install --no-cache-dir '.[service,mcp-server]'
COPY evals ./evals
COPY service ./service
COPY mcp_servers ./mcp_servers
COPY deploy/healthcheck.py ./deploy/healthcheck.py
RUN useradd --uid 10001 --create-home corecoder \
    && mkdir -p /app/.tmp/service \
    && chown 10001:10001 /app/.tmp/service
USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "service.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

FROM runtime AS validation
USER root
RUN python -m pip install --no-cache-dir 'pytest>=7,<10'
COPY tests ./tests
COPY deploy ./deploy
USER 10001:10001
