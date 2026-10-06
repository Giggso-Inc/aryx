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
#
# Multi-arch: Oracle ships separate x86_64 and arm64 Instant Client
# archives under different version numbers and directory names (confirmed
# live, 2026-10-06 -- this build was failing on an arm64 dev host: the
# x86_64 zip was always downloaded, and /lib/x86_64-linux-gnu/ doesn't
# exist on arm64, so the libaio symlink step failed outright). Detect the
# architecture at build time and pick the matching archive/sha256/multiarch
# triplet; always symlink the extracted, version-numbered directory to the
# stable /opt/oracle/instantclient_current so LD_LIBRARY_PATH (and this
# image's runtime code) never needs to know which version got installed.
ENV LD_LIBRARY_PATH=/opt/oracle/instantclient_current
RUN set -eux; \
    apt-get update && apt-get install -y --no-install-recommends \
        wget unzip libaio1t64; \
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
    wget -q "$ic_url" -O /tmp/instantclient.zip; \
    # Oracle doesn't publish a checksum for either artifact; these pin the
    # digests fetched and verified when this was added, catching tampering
    # or an unexpected content change rather than silently trusting TLS alone.
    echo "$ic_sha256  /tmp/instantclient.zip" | sha256sum -c -; \
    mkdir -p /opt/oracle; \
    unzip -q /tmp/instantclient.zip -d /opt/oracle; \
    rm /tmp/instantclient.zip; \
    # `ln -s` succeeds even if its target doesn't exist -- if the archive
    # ever extracts to a different directory name than $ic_dir (version
    # bump, Oracle changing their packaging), this build must fail loudly
    # here, not silently ship a broken symlink that only surfaces as a
    # fallback-to-thin-mode log line at runtime.
    test -d "/opt/oracle/${ic_dir}"; \
    ln -s "/opt/oracle/${ic_dir}" /opt/oracle/instantclient_current; \
    # Oracle's client binary dlopen()s the old "libaio.so.1" name; this
    # base image only ships "libaio.so.1t64" (Debian's 64-bit time_t
    # package rename) -- confirmed live, DPI-1047 without this symlink.
    ln -s "/lib/${multiarch}/libaio.so.1t64" "/lib/${multiarch}/libaio.so.1"; \
    apt-get purge -y --auto-remove wget unzip; \
    rm -rf /var/lib/apt/lists/*

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
