# Dutch Tutor: FastAPI backend that also serves the frontend.
# The repo layout is kept (backend/, frontend/, spec at the root) because the
# app locates the frontend and the agent spec relative to its own code.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app/backend

COPY backend/requirements.txt .
RUN pip install -r requirements.txt

COPY backend/app ./app
COPY frontend /app/frontend
COPY dutch-tutor-agent-spec.md /app/

# Learner data (JSON per user) and the sign-in signing key live in data/;
# mount a persistent volume there in production.
RUN useradd --uid 10001 --no-create-home app \
    && mkdir -p data/users \
    && chown -R app data
USER 10001

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"

# One worker: the file-based store and the sign-in throttle are per-process.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
