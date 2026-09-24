# The workbench and the CLI in a container: Chromium for rendering, ffmpeg for clips, no GPU.
# The workspace -- fonts/, art/, sets/, styles/, the card file, mint.toml -- is a volume at
# /workspace; the image carries only code. ComfyUI is reached over the network: COMFY_URL,
# and COMFY_TOKEN when that server sits behind an authenticating proxy (a GPU host elsewhere).
# compose.yaml wires the environment and the volume; `docker compose up -d` is the whole start.
FROM python:3.13-slim

ENV PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    MINT_HOME=/workspace HOME=/tmp

# ffmpeg encodes animate's clips; Liberation is the fallback face Chromium reaches for when a frame font is missing
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# the dependencies and Chromium first, so a code change rebuilds neither
RUN pip install "playwright>=1.40" "pillow>=10" "fonttools>=4.40" "fastapi>=0.110" "uvicorn>=0.27" \
    && playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/* \
    && chmod -R a+rX /ms-playwright

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY mint ./mint
RUN pip install --no-deps .

# files the container writes into the workspace belong to this uid; compose's `user:` overrides it.
# The workspace is also the working directory, so a relative --out lands there, as it does on a desktop
USER 1000:1000
VOLUME /workspace
WORKDIR /workspace
EXPOSE 8300
CMD ["mint", "serve", "--host", "0.0.0.0", "--port", "8300"]
