# Aryx worker image — 12-factor, slim Python base. Portable across
# ECS / EKS / OCI (orchestrator chosen at rollout, not build time).
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    python -m spacy download en_core_web_lg

COPY src/ ./src/

# Per-catalog CPQ native-UI layout exports (docs/CPQ_LAYOUT_TXT_VISIBILITY_
# ORDER_PLAN.md) — one file per catalog, matched by catalog name substring
# in the filename (e.g. "Config Layout APX Next.txt" for "Apx Next").
# ARYX_CPQ_LAYOUT_DIR (docker-compose.yml) points CpqEngine's
# LocalDirLayoutFileSource at this directory.
COPY config_layouts/ ./config_layouts/

# Streamlit theme config — must live at /app/.streamlit so the UI process
# (started from WORKDIR=/app) picks it up instead of falling back to the
# browser's prefers-color-scheme (which renders dark and kills sidebar
# contrast against our light gradient).
COPY .streamlit ./.streamlit

CMD ["python", "-m", "aryx"]
