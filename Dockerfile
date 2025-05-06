# syntax=docker/dockerfile:1
FROM --platform=$TARGETPLATFORM python:3.11-slim AS runtime
WORKDIR /app

# Only runtime deps (cryptography) to keep image small
COPY dev-requirements.txt ./
RUN pip install --no-cache-dir cryptography==42.0.5

# Copy source
COPY src ./src
ENV PYTHONPATH=/app/src

# Expose default port
ENV BEER_PORT=5000
EXPOSE 5000

# Default command = run server; can be overridden: `docker run beer-client python -m beer.client …`
CMD ["python", "-m", "beer.server"]
