# MusicLounge Player — production image
# Same shape as musiclounge's Dockerfile (Ubuntu 24.04 + gunicorn),
# for consistency across the product family.

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.12 \
        python3.12-venv \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN python3.12 -m venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x docker-entrypoint.sh

# Bake config.example.py in as the default config.py -- same
# reasoning as musiclounge's Dockerfile: .dockerignore excludes any
# real local config.py from the build context, so this only ever
# copies the placeholder template. Real values come from environment
# variables at runtime.
RUN cp config.example.py config.py

RUN mkdir -p /app/data

EXPOSE 8680

ENTRYPOINT ["./docker-entrypoint.sh"]
