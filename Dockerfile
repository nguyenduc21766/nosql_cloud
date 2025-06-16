###############################################################################
# Image : databasecourse-nosql-api
# Base  : Ubuntu 24.04 
###############################################################################
FROM ubuntu:24.04
ARG TZ=Europe/Helsinki

# ── 0. Setup ────────────────────────────────────────────────────────────────
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo "$TZ" > /etc/timezone

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get upgrade -y

# Convenience macro
ENV apt='apt-get --no-install-recommends install -yq'

# Base utilities + systemd support
RUN $apt sudo nano curl gnupg2 acl unzip git wget less vim lsb-release gpg \
    systemd systemd-sysv build-essential tcl pkg-config python3 python3-pip python3-setuptools

# ── 1. Python deps ──────────────────────────────────────────────────────────
RUN pip3 install --no-cache-dir fastapi uvicorn redis pymongo

# ── 2. Redis 7.0.15 from source ─────────────────────────────────────────────
ARG REDIS_VERSION=7.0.15
RUN curl -fsSL https://download.redis.io/releases/redis-${REDIS_VERSION}.tar.gz | tar xz -C /tmp && \
    make -C /tmp/redis-${REDIS_VERSION} && \
    make -C /tmp/redis-${REDIS_VERSION} install && \
    mkdir -p /etc/redis && \
    cp /tmp/redis-${REDIS_VERSION}/redis.conf /etc/redis/redis.conf && \
    sed -i 's/^protected-mode yes/protected-mode no/' /etc/redis/redis.conf && \
    sed -i 's/^bind .*/# &/' /etc/redis/redis.conf && \
    printf "[Unit]\nDescription=Redis In-Memory Data Store\nAfter=network.target\n\n[Service]\nExecStart=/usr/local/bin/redis-server /etc/redis/redis.conf\nRestart=always\nUser=root\n\n[Install]\nWantedBy=multi-user.target\n" \
      > /etc/systemd/system/redis.service && \
    systemctl enable redis.service

# ── 3. MongoDB 7.0.5 binary ─────────────────────────────────────────────────
ARG MONGO_VERSION=7.0.5
ARG MONGO_PKG=mongodb-linux-x86_64-ubuntu2204-${MONGO_VERSION}
RUN curl -fsSL https://fastdl.mongodb.org/linux/${MONGO_PKG}.tgz -o /tmp/mongo.tgz && \
    tar -xzf /tmp/mongo.tgz -C /opt && \
    ln -s /opt/${MONGO_PKG}/bin/* /usr/local/bin && \
    mkdir -p /data/db && \
    printf "storage:\n  dbPath: /data/db\nnet:\n  bindIp: 0.0.0.0\n" > /etc/mongod.conf && \
    printf "[Unit]\nDescription=MongoDB Database Server\nAfter=network.target\n\n[Service]\nExecStart=/usr/local/bin/mongod --config /etc/mongod.conf\nRestart=always\nUser=root\n\n[Install]\nWantedBy=multi-user.target\n" \
      > /etc/systemd/system/mongod.service && \
    systemctl enable mongod.service

# ── 4. FastAPI service file + app ───────────────────────────────────────────
COPY docker/fastapi.service /etc/systemd/system/fastapi.service
COPY . /app
RUN systemctl enable fastapi.service

# ── 5. Systemd inside container ─────────────────────────────────────────────
RUN mkdir -p /run/systemd && echo 'docker' > /run/systemd/container

EXPOSE 80
CMD ["/sbin/init"]
