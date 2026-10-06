# Log Analyzer Backend Dockerfile

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    libmagic1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Oracle Instant Client (thick-mode python-oracledb, sync engine only -- see
# docs/oci-oracle/ORACLE_THICK_MODE_MIGRATION_PLAN_2026-10-06.md "shay-api"
# section). Run as root, before the USER appuser switch below, so appuser
# can still read (not write) these files. libaio1t64 (not the historically
# common libaio1 -- Debian's 64-bit time_t package rename) and the
# libaio.so.1 symlink are both confirmed required on this base image
# (same findings as the main Dockerfile's Instant Client install).
#
# Multi-arch: see the main Dockerfile's identical block for why -- Oracle
# ships separate x86_64/arm64 archives under different version numbers and
# directory names; detect architecture at build time and always symlink to
# the stable /opt/oracle/instantclient_current.
ENV LD_LIBRARY_PATH=/opt/oracle/instantclient_current
RUN set -eux; \
    apt-get update && apt-get install -y --no-install-recommends \
        unzip libaio1t64; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
        amd64) \
            ic_url="https://download.oracle.com/otn_software/linux/instantclient/2380000/instantclient-basiclite-linux.x64-23.8.0.25.04.zip"; \
            ic_sha256="208bc7a9372efae098ab743d6e76aeb66e6f42579dcdbb7a6a8438412481b02e"; \
            ic_dir="instantclient_23_8"; \
            multiarch="x86_64-linux-gnu"; \
            ;; \
        arm64) \
            ic_url="https://download.oracle.com/otn_software/linux/instantclient/2326300/instantclient-basiclite-linux.arm64-23.26.3.0.0.zip"; \
            ic_sha256="6559d63a81133e821cbf7fd81d023827813f3262a1ea45a32d364eeeccc68579"; \
            ic_dir="instantclient_23_26"; \
            multiarch="aarch64-linux-gnu"; \
            ;; \
        *) \
            echo "Unsupported architecture for Oracle Instant Client: $arch" >&2; \
            exit 1; \
            ;; \
    esac; \
    # -f makes an HTTP error fail the build instead of silently downloading
    # an error page that only fails later, confusingly, at unzip.
    curl -fsSL "$ic_url" -o /tmp/instantclient.zip; \
    # Oracle doesn't publish a checksum for either artifact; these pin the
    # digests fetched and verified when this was added (same files as the
    # main Dockerfile's Instant Client install).
    echo "$ic_sha256  /tmp/instantclient.zip" | sha256sum -c -; \
    mkdir -p /opt/oracle; \
    unzip -q /tmp/instantclient.zip -d /opt/oracle; \
    rm /tmp/instantclient.zip; \
    ln -s "/opt/oracle/${ic_dir}" /opt/oracle/instantclient_current; \
    ln -s "/lib/${multiarch}/libaio.so.1t64" "/lib/${multiarch}/libaio.so.1"; \
    chmod -R a+rX /opt/oracle; \
    apt-get purge -y --auto-remove unzip; \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create uploads directory
RUN mkdir -p uploads

# Create non-root user
RUN adduser --disabled-password --gecos '' appuser
RUN chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=60s --retries=5 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
