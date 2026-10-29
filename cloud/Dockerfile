FROM python:3.12-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    CHROME_BIN=/usr/bin/chromium \
    CHROMEDRIVER=/usr/bin/chromedriver

RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium \
        chromium-driver \
        fonts-ipafont-gothic \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements-cloud.txt .
RUN pip install --no-cache-dir -r requirements-cloud.txt

COPY template_engine.py browser_actions.py clipboard_utils.py paths.py shared_log.py ./
COPY templates ./templates
COPY write_once.py server.py result_sheet.py navi_callback.py verify_karte.py ./

# 受け口（Service）。Job の手動試験は python write_once.py で上書き可能
CMD ["python", "server.py"]
