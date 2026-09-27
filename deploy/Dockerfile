# One image for the API, the live pipeline and the worker (deploy/compose.yml picks the command).
# libgl1/libglib2.0: OpenCV. libxrender1: the SUMO binary from eclipse-sumo.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# CPU-only torch first, so ultralytics doesn't pull the multi-GB CUDA build
RUN pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
COPY pyproject.toml README.md ./
COPY common common
COPY ingest ingest
COPY vision vision
COPY events events
COPY signals signals
COPY sim sim
COPY api api
COPY evaluation evaluation
COPY scripts scripts
COPY data data
RUN pip install ".[vision,sim,llm]"
# weights baked in, so a restart never waits on a download
RUN python -c "from ultralytics import YOLO; YOLO('yolo11s.pt')"
