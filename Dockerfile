# Aryx worker image — 12-factor, slim Python base. Portable across
# ECS / EKS / OCI (orchestrator chosen at rollout, not build time).
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src:/app

# Oracle Instant Client (thick-mode python-oracledb) -- see docs/oci-oracle/
# ORACLE_THICK_MODE_MIGRATION_PLAN_2026-10-06.md. Gated at runtime behind
# ARYX_ORACLE_CLIENT_MODE (src/aryx/api/main_oracle_client.py); installed
# unconditionally here since the image is built once and the mode is a
# cheap env-var flip, not a rebuild. libaio1t64 (not the historically
# common libaio1 -- Debian's 64-bit time_t package rename) is the one
# confirmed missing system dependency on this base image. unzip (not
# Python's zipfile module) preserves the package's internal symlinks
# (e.g. libclntsh.so -> libclntsh.so.23.1) -- zipfile.extractall() does
# not, confirmed live while building this.
ENV LD_LIBRARY_PATH=/opt/oracle/instantclient_23_8
RUN apt-get update && apt-get install -y --no-install-recommends \
        wget unzip libaio1t64 \
    && wget -q https://download.oracle.com/otn_software/linux/instantclient/2380000/instantclient-basiclite-linux.x64-23.8.0.25.04.zip \
        -O /tmp/instantclient.zip \
    # Oracle doesn't publish a checksum for this artifact; this pins the
    # digest fetched and verified when this was added, catching tampering
    # or an unexpected content change rather than silently trusting TLS alone.
    && echo "208bc7a9372efae098ab743d6e76aeb66e6f42579dcdbb7a6a8438412481b02e  /tmp/instantclient.zip" | sha256sum -c - \
    && mkdir -p /opt/oracle \
    && unzip -q /tmp/instantclient.zip -d /opt/oracle \
    && rm /tmp/instantclient.zip \
    # Oracle's client binary dlopen()s the old "libaio.so.1" name; this
    # base image only ships "libaio.so.1t64" (Debian's 64-bit time_t
    # package rename) -- confirmed live, DPI-1047 without this symlink.
    && ln -s /lib/x86_64-linux-gnu/libaio.so.1t64 /lib/x86_64-linux-gnu/libaio.so.1 \
    && apt-get purge -y --auto-remove wget unzip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    python -m spacy download en_core_web_lg

COPY src/ ./src/
COPY sales_streamlit/ ./sales_streamlit/

# Streamlit theme config — must live at /app/.streamlit so the UI process
# (started from WORKDIR=/app) picks it up instead of falling back to the
# browser's prefers-color-scheme (which renders dark and kills sidebar
# contrast against our light gradient).
COPY .streamlit ./.streamlit

CMD ["python", "-m", "aryx"]
