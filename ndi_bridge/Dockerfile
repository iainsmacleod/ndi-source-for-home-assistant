# NDI Bridge addon: receives NDI, serves MJPEG + discovery API
# build.yaml supplies BUILD_FROM (e.g. python:3.11-slim-bookworm)
ARG BUILD_FROM
FROM $BUILD_FROM

RUN apt-get update && apt-get install -y --no-install-recommends \
    libavahi-client3 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    cyndilib \
    aiohttp \
    Pillow

WORKDIR /app
COPY server.py /app/
COPY run.sh /app/

RUN chmod +x /app/run.sh

EXPOSE 8080
CMD ["/app/run.sh"]
