FROM node:24-bookworm

ARG RELAY_REPO=https://github.com/fa0311/twitter_api_safe_relay.git
ARG RELAY_REF=main

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      chromium \
      curl \
      fonts-liberation \
      git \
      python3 \
      python3-pip \
      python3-venv \
      tini \
    && rm -rf /var/lib/apt/lists/*

RUN corepack enable && corepack prepare pnpm@11.10.0 --activate

ENV CHROME_BIN=/usr/bin/chromium \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN git clone --depth 1 --branch "$RELAY_REF" "$RELAY_REPO" /app/relay \
    && cd /app/relay \
    && pnpm install --frozen-lockfile \
    && pnpm build:relay

COPY docker/relay-settings.active.json /app/relay/settings.json

COPY requirements.txt /app/santasan/requirements.txt
RUN python3 -m venv /app/santasan/.venv \
    && /app/santasan/.venv/bin/pip install --no-cache-dir --upgrade pip \
    && /app/santasan/.venv/bin/pip install --no-cache-dir -r /app/santasan/requirements.txt

COPY generator_node/package.json generator_node/package-lock.json /app/santasan/generator_node/
RUN cd /app/santasan/generator_node && npm ci

COPY . /app/santasan/
COPY docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["tini", "--", "/app/entrypoint.sh"]
CMD ["run"]
