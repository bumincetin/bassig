# BASSIGNANA EPC CONTROL -- container image for a shared company server.
#
# Every piece of live data (database, photographs, backups, source documents,
# secret key, logs) lives under /data. Mount a persistent volume there, or a
# redeploy will start from an empty project record.
#
#   docker build -t bassignana-epc-control .
#   docker run -d --name bassignana -p 8080:8080 \
#       -v bassignana-data:/data \
#       -e BASSIGNANA_ACCESS_PASSWORD='choose-a-strong-shared-password' \
#       bassignana-epc-control
#
# See deploy/HOSTING.md for the full walk-through.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BASSIGNANA_DATA_DIR=/data \
    BASSIGNANA_PORT=8080 \
    BASSIGNANA_BEHIND_PROXY=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin bassignana \
 && mkdir -p /data \
 && chown -R bassignana:bassignana /app /data

USER bassignana
VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=60s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('BASSIGNANA_PORT', '8080'), timeout=4)"

CMD ["python", "run.py"]
