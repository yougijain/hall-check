# Detection runs on CPU, so this is a plain slim image with no CUDA layers.
FROM python:3.11-slim

# ffmpeg is how frames are pulled from the HLS streams; without it the worker
# starts fine and then fails every capture, so it belongs in the image rather
# than in a start-up script.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    # Ultralytics otherwise writes a settings file and a datasets directory
    # into $HOME on first import; point both somewhere writable and ephemeral.
    YOLO_CONFIG_DIR=/tmp/ultralytics \
    MPLCONFIGDIR=/tmp/matplotlib

WORKDIR /app

# Dependencies first so a code change does not re-resolve the whole tree.
COPY pyproject.toml ./
RUN python -m pip install --upgrade pip \
    && python -m pip install --no-cache-dir .

COPY hallcheck ./hallcheck

# Bake the weights in. Fetching them on first run makes a cold start depend on
# a third-party host being up, and turns a redeploy into a silent five-minute
# outage when it is not.
#
# .github/workflows/publish-worker.yml proves this held, by loading the model
# in the built image with the network disabled. If the weights ever stop being
# baked, the container would quietly reach out on first run instead and only
# fail when that host is down - which is exactly the failure this avoids.
RUN python -c "from ultralytics import YOLO; YOLO('yolo11n.pt')"

# Not root. The worker needs no filesystem access beyond /app and its cache
# directories, all of which are created here so the chown cannot silently miss
# one.
RUN mkdir -p "$YOLO_CONFIG_DIR" "$MPLCONFIGDIR" \
    && useradd --create-home --uid 10001 worker \
    && chown -R worker:worker /app "$YOLO_CONFIG_DIR" "$MPLCONFIGDIR"
USER worker

CMD ["python", "-m", "hallcheck.cli", "run"]
