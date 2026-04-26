FROM python:3.12-slim

# docker CLI (static), gzip/tar for backups, ca-certificates for HTTPS
RUN apt-get update && apt-get install -y --no-install-recommends \
        gzip tar curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL https://download.docker.com/linux/static/stable/x86_64/docker-27.3.1.tgz \
        | tar -xz -C /usr/local/bin --strip-components=1 docker/docker \
    && docker --version

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ /app/

EXPOSE 9990
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9990", "--workers", "1"]
