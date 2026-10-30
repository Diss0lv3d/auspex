# A stub SIEM for the S33 live check only (compose's dev profile): the reference
# connector's health endpoint over HTTPS, with a self-signed certificate made at start.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends openssl \
    && rm -rf /var/lib/apt/lists/*
COPY server.py /srv/server.py
EXPOSE 8443
CMD ["python", "/srv/server.py"]
