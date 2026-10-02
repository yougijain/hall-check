# Detection runs on CPU. The base image carries no CUDA, and neither do the
# wheels - see the torch install below, which is the part that actually
# decides.
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

# torch comes first, and from PyTorch's CPU index rather than PyPI.
#
# ultralytics depends on torch, and the torch wheel PyPI serves for linux
# x86_64 is the CUDA build: it vendors cuDNN, cuBLAS, NCCL and the rest of the
# NVIDIA runtime, well over a gigabyte of it. Installing the package without
# pinning an index drags all of that onto a machine that has no GPU and never
# will - the model is YOLO11n on a frame every two minutes.
#
# The cost is not only disk. A larger image is slower to pull on every cold
# start and every redeploy, and the resident footprint is what decides which
# instance tier this fits on, which is a real monthly number.
#
# Installing torch first means the ultralytics install below resolves its
# torch requirement against what is already present instead of fetching the
# PyPI wheel. Pinning the index on both commands would be the belt-and-braces
# version; it is one index for one package, and the second command needs PyPI
# for everything else.
RUN python -m pip install --upgrade pip \
    && python -m pip install --no-cache-dir \
        torch --index-url https://download.pytorch.org/whl/cpu \
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
