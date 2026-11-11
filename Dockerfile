# Headless Chromium + Python, multi-arch (amd64 / arm64). The playwright package below
# must match the image tag, because the browsers are baked into the image.
FROM mcr.microsoft.com/playwright/python:v1.65.0-noble

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data WWW_DIR=/www PORT=8097

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY familydash ./familydash
COPY roku ./roku
RUN pip install --no-cache-dir --break-system-packages playwright==1.55.0 \
 && pip install --no-cache-dir --break-system-packages --no-deps . \
 && mkdir -p /data /www && chown pwuser:pwuser /data /www

USER pwuser
EXPOSE 8097
VOLUME ["/data"]
# healthy = an image rendered within the last 3 minutes
HEALTHCHECK --interval=60s --timeout=5s --start-period=90s \
  CMD python -c "import os,time,sys; sys.exit(time.time()-os.path.getmtime('/www/dashboard.jpg')>180)"
CMD ["python", "-m", "familydash", "serve"]
