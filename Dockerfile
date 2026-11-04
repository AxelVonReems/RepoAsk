# The API image: FastAPI + the embedding model + a prebuilt data/index.db, nothing else.
# The container only reads; ingest and indexing run in GitHub Actions (see the plan).
#
#   docker build -t repoask .
#   docker run --rm -p 8000:8000 -e GEMINI_API_KEY repoask
#
# data/index.db must exist before the build: locally from `python -m rag.indexing.build_index`,
# in CI downloaded from the index-latest release.

# Both stages use the same base, so the virtualenv built in one runs unchanged in the other
ARG PYTHON_IMAGE=python:3.12-slim

# ---- build: install dependencies and download the model ----
FROM ${PYTHON_IMAGE} AS build

# uv as a single static binary, same version as CI
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /bin/uv

# Compile .pyc now so the first request after a cold start doesn't pay for it; use the image's
# Python instead of downloading one; copy files out of the cache mount instead of hard-linking
ENV UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy

WORKDIR /app

# Dependencies first, in their own layer: it is rebuilt only when uv.lock changes, not on every
# code edit. --no-dev leaves out pytest/ruff; --no-install-project because the code is not
# installed as a package, it runs from /app (see CMD).
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project

COPY rag ./rag

# Bake the model in: the container never downloads anything at startup. Loading the embedder
# the same way the API does puts the files exactly where config.MODEL_CACHE_DIR expects them.
# Some cache files are written owner-only (0600); the non-root user must be able to read them.
RUN .venv/bin/python -c "from rag.indexing.embed import FastEmbedEmbedder; FastEmbedEmbedder()" \
    && chmod -R a+rX .cache

# ---- runtime: only what the API needs ----
FROM ${PYTHON_IMAGE}

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HUB_OFFLINE=1

# A system user with no shell and no home: if the app is ever compromised, it is not root
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app

# Owned by root and read-only for `app`: the API never writes (index.db is opened ?mode=ro)
COPY --from=build /app/.venv ./.venv
COPY --from=build /app/.cache ./.cache
COPY rag ./rag
COPY data/index.db ./data/index.db

USER app

EXPOSE 8000

# `python -m` puts /app on sys.path, so `rag` imports without being installed. Exec form: uvicorn
# is PID 1 and gets SIGTERM directly when Container Apps stops the replica, so it shuts down
# cleanly instead of being killed after the timeout.
CMD ["python", "-m", "uvicorn", "rag.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
