FROM python:3.12-slim

# iputils-ping provides the ICMP fallback used when a TCP port check fails
RUN apt-get update \
    && apt-get install -y --no-install-recommends iputils-ping \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY web/requirements.txt web/requirements.txt
RUN pip install --no-cache-dir -r web/requirements.txt

COPY web/ web/

# Settings, server list, SMS config, logs and status live here - mount a volume
ENV NOC_DATA_DIR=/data \
    NOC_PORT=8082 \
    PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8082

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/login' % os.environ.get('NOC_PORT','8082'), timeout=4)"

CMD ["python", "web/noc_web.py"]
