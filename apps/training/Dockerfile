FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp
WORKDIR /opt/training
COPY requirements.lock ./
RUN python -m pip install --no-cache-dir --require-hashes -r requirements.lock

COPY train.py ./
USER 10001:10001
ENTRYPOINT ["python", "train.py"]
