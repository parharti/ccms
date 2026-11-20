# Backend image built from the REPO ROOT -- for hosts (e.g. a Render web
# service with no Root Directory set) that look for ./Dockerfile at the top
# of the repo. Same image as backend/Dockerfile, which docker-compose and
# render.yaml use.
FROM python:3.13-slim

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/scripts ./scripts

# JD PDFs and candidate documents are written under /app/storage.
RUN mkdir -p storage

EXPOSE 8000

# Honour $PORT when the host sets it (Render does), default 8000.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
