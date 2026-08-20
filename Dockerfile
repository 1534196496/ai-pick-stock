FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --system app \
    && useradd --system --gid app --create-home --home-dir /home/app app

COPY requirements.lock pyproject.toml ./
RUN python -m pip install --upgrade pip \
    && python -m pip install --requirement requirements.lock

COPY src ./src
COPY dashboard.py config.toml ./
COPY .streamlit ./.streamlit

RUN python -m pip install --no-deps . \
    && mkdir -p /app/data /app/reports /app/logs /app/backups \
    && chown -R app:app /app /home/app

USER app

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3)" || exit 1

CMD ["streamlit", "run", "dashboard.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true", "--browser.gatherUsageStats=false"]
