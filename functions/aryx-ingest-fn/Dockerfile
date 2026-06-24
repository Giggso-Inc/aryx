# aryx OCI Functions image — ARM64 (A1.Flex).
# Build context: repo root (aryx/).
#
# Build:
#   docker build --platform linux/arm64 \
#     -t <registry>/aryx/aryx-ingest-fn:latest \
#     -f functions/aryx-ingest-fn/Dockerfile .
# Pinned ARM64 digest — update with: docker manifest inspect python:3.13-slim
FROM python:3.13-slim@sha256:2a0c4c36359b0ab47018161d37b2ce2d9c5bd9c3c60879b747559cd4275d9332

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src

# System deps required by aryx document processing libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY functions/aryx-ingest-fn/requirements_oci.txt .
# fdk is OCI Functions Python runtime — not in main requirements (local dev doesn't need it)
RUN pip install --no-cache-dir fdk -r requirements_oci.txt
RUN python -m spacy download en_core_web_sm

COPY src/ ./src/

# OCI Functions runtime invokes the handler via the fdk CLI
CMD ["fdk", "aryx.worker.fn_handler:handler"]
