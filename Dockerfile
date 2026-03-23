# ── PulseTrace Dockerfile ─────────────────────────────────────────────────────
# Optimised for HuggingFace Spaces (Docker SDK).
#
# HuggingFace Spaces requirements:
#   • Non-root user with UID 1000
#   • Port 7860 (default Streamlit port for Spaces)
#   • COPY before RUN for layer-cache efficiency
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.11-slim

# HuggingFace Spaces requires a non-root user with UID 1000
RUN useradd -m -u 1000 user

WORKDIR /app

# ── Install dependencies (cached layer — only rebuilds when requirements change)
COPY --chown=user requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ── Copy application source
COPY --chown=user . .

# Ensure the .streamlit directory is present (config.toml is committed)
RUN mkdir -p .streamlit

# Give the non-root user write access to /app so SQLite can create pulsetrace.db
RUN chown -R user:user /app

# ── Switch to non-root user for runtime
USER user

# Port 7860 is the HuggingFace Spaces default for Streamlit apps
EXPOSE 7860

# Health check using Streamlit's built-in health endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:7860/_stcore/health')" || exit 1

# Launch Streamlit — flags match .streamlit/config.toml for redundancy
CMD ["streamlit", "run", "app.py", \
     "--server.port=7860", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--server.enableCORS=false", \
     "--server.enableXsrfProtection=false", \
     "--browser.gatherUsageStats=false"]
