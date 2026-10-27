# LeadDesk public demo image: fictional data, internet actions off, AI rewording on NVIDIA Nemotron via Nebius Token Factory.
# Build:  docker build -t leaddesk-demo .
# Run:    docker run -p 8765:8765 -e NEBIUS_API_KEY=... -e LEADDESK_PUBLIC_HOST=your.domain leaddesk-demo
FROM node:24.21.0-slim AS web
WORKDIR /src/apps/web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY apps/web/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LEADDESK_DATA_DIR=/data LEADDESK_DEMO=1
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir --default-timeout=60 -r requirements.lock
COPY backend/ backend/
COPY scripts/build_demo_data.py scripts/
COPY deploy/demo/entrypoint.sh deploy/demo/entrypoint.sh
COPY --from=web /src/apps/web/dist apps/web/dist
# The fictional demo data is built once, offline, into the image; every container start copies a fresh set.
RUN python scripts/build_demo_data.py /app/demo-template && useradd --create-home leaddesk && mkdir /data && chown leaddesk /data
USER leaddesk
EXPOSE 8765
ENTRYPOINT ["sh", "deploy/demo/entrypoint.sh"]
