# aryx OCI Functions image — ARM64 (A1.Flex).
# Build context: repo root (aryx/).
#
# Before building, unzip the ADB wallet into this directory:
#   unzip wallet.zip -d functions/aryx-ingest-fn/wallet/
#
# Build:
#   docker build --platform linux/arm64 \
#     -t <registry>/aryx/aryx-ingest-fn:latest \
#     -f functions/aryx-ingest-fn/Dockerfile .
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src

# System deps required by aryx document processing libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libmupdf-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
# fdk is OCI Functions Python runtime — not in main requirements (local dev doesn't need it)
RUN pip install --no-cache-dir fdk -r requirements.txt

COPY src/ ./src/

# ADB wallet — must be present at build time.
# DevOps unzips wallet.zip into functions/aryx-ingest-fn/wallet/ before docker build.
# The wallet directory is gitignored — never committed.
COPY functions/aryx-ingest-fn/wallet/ /opt/oracle/wallet/aryx/
ENV TNS_ADMIN=/opt/oracle/wallet/aryx

# OCI Functions runtime invokes the handler via the fdk CLI
CMD ["fdk", "aryx.worker.fn_handler:handler"]
