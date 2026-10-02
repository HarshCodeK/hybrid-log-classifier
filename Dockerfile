# syntax=docker/dockerfile:1
#
# Every layer is explained, because "what's in your Dockerfile?" is a real
# interview question and an unexplained one is indistinguishable from a
# copied one.

FROM python:3.12-slim

# Why 3.12 and not 3.14: 3.12 is the newest version where scikit-learn,
# pandas and numpy all ship prebuilt wheels for every platform. On 3.14 the
# BLAS libraries fall back to a source build or fail at import on some
# machines -- which is exactly the "works on my machine" trap.
FROM python:3.12-slim AS base

# PYTHONDONTWRITEBYTECODE stops .pyc files being written into the image.
# PYTHONUNBUFFERED makes logs appear immediately instead of sitting in a
# buffer, which matters when the container is the only place you can see them.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies are copied and installed BEFORE the source code. This layer is
# cached until requirements.txt itself changes, so editing a .py file does not
# trigger a full reinstall of scikit-learn. That one ordering decision is the
# difference between a 3-second and a 3-minute rebuild.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY static/ ./static/
COPY tests/ ./tests/
COPY data/ ./data/
COPY train.py ./

# Run as a non-root user. A container that runs as root inside its own
# namespace still has far less authority than root on the host, but not being
# root is one free habit.
RUN useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# The health check uses the API's own endpoint rather than a bare TCP connect,
# because a listening port says nothing about whether the app can serve
# requests. This is what makes an orchestrator restart a genuinely broken
# container instead of a merely-running one.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"

# --host 0.0.0.0 rather than the default 127.0.0.1: inside a container the
# server must listen on all interfaces to be reachable from the host. Binding to
# localhost in a container means the published port connects to nothing.
CMD ["python", "-m", "uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000"]
