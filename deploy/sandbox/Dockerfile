FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8
RUN useradd --uid 10001 --no-create-home sandbox
USER 10001:10001
WORKDIR /tmp
# Current trusted task bundles use stdlib unittest and bundled repository code.
# Additional repository dependencies must be installed here, never at test time.
