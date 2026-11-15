# Vikri Kavach: one container serves the React app and the API on port 8080.
# Build from the repository root (it needs the shared bhavsetu package):
#   docker build -f vikrikavach/Dockerfile -t vikrikavach .

FROM node:22-alpine AS web
WORKDIR /web
COPY vikrikavach/frontend/package.json vikrikavach/frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY vikrikavach/frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv
COPY bhavsetu/ /src/bhavsetu/
COPY vikrikavach/backend/ /srv/
RUN pip install /src/bhavsetu /srv && rm -rf /src
COPY --from=web /web/dist /srv/static
RUN useradd --system --uid 10001 --home /srv app && mkdir -p /srv/var && chown -R app /srv/var
USER app
ENV STATIC_DIR=/srv/static PORT=8080 WEB_CONCURRENCY=2
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=4).status == 200 else 1)"
CMD ["sh", "-c", "exec gunicorn 'app.main:build()' -k uvicorn.workers.UvicornWorker -b 0.0.0.0:${PORT} -w ${WEB_CONCURRENCY} --timeout 90 --control-socket /tmp/gunicorn.ctl --access-logfile -"]
