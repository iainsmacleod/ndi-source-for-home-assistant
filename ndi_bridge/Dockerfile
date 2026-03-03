# NDI Bridge addon: receives NDI, serves MJPEG + discovery API
# build.yaml supplies BUILD_FROM (Home Assistant base-python image)
ARG BUILD_FROM
FROM $BUILD_FROM

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
