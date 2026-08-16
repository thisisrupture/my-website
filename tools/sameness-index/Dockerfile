# Why a Dockerfile and not Render's Python runtime.
#
# The crawler needs a real browser for the sites that build their copy in one,
# and a browser is an operating system problem, not a pip problem: Chromium
# wants a few dozen shared libraries that a managed Python runtime does not
# have and does not let you install. So the image is built here, once, and
# Render runs it.
#
# The browser is installed at build time and lives in the image. Nothing is
# downloaded when the service starts, which matters: a cold start that fetches
# 150MB of Chromium is a cold start that fails its health check.

FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# Requirements first, and on their own layer: the code changes on every push,
# the dependencies almost never, and Chromium takes minutes to install.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
 && playwright install --with-deps chromium \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

COPY . .

# Render sets PORT. The default is only for running the image by hand.
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}"]
