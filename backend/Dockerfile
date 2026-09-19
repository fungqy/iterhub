FROM python:3.13-slim

WORKDIR /app

ENV UV_SYSTEM_PYTHON=1

RUN pip install uv

COPY pyproject.toml uv.lock ./

RUN uv pip install --system -r pyproject.toml

COPY src/ ./src/
COPY logging.conf .
COPY scripts/run.sh ./scripts/

RUN chmod +x scripts/run.sh

RUN mkdir -p logs

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)" || exit 1

CMD ["./scripts/run.sh"]
