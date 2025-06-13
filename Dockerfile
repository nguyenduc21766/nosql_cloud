###############################################################################
# Image : databasecourse-nosql-api
# Base  : Ubuntu 24.04 (noble) – pinned DB & Python package versions
###############################################################################
FROM ubuntu:24.04
ARG TZ=Europe/Helsinki

# ── 0.  House-keeping ────────────────────────────────────────────────────────
RUN ln -snf /usr/share/zoneinfo/${TZ} /etc/localtime \
 && echo "${TZ}" > /etc/timezone

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    MONGO_MAJOR=6.0 \
    MONGO_VER=6.0.14

RUN apt-get update && apt-get upgrade -y

# convenience macro  
ENV apt='apt-get --no-install-recommends install -yq'

RUN $apt sudo systemctl nano curl gnupg2 acl unzip git wget less vim lsb-release gpg

# Create a non-root workspace (optional – you can stay as root like teacher)
RUN mkdir -p /home/root
WORKDIR /home/root

# ── 1.  Python +  FastAPI app  ──────────────────────────────────────────────
RUN $apt python3 python3-pip python3-setuptools
ENV PIP_BREAK_SYSTEM_PACKAGES=1       

RUN pip3 install --no-cache-dir \
        fastapi uvicorn redis pymongo

# ── 2.  Redis 7.0.x  (official apt repo) ────────────────────────────────────
# ── 2. Redis 7.x from packages.redis.io (jammy repo) ──────────────────────
# ── 2. Redis 7.x from packages.redis.io (fixed repo) ──────────────────────
RUN curl -fsSL https://packages.redis.io/gpg | \
    gpg --dearmor -o /usr/share/keyrings/redis-archive-keyring.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/redis-archive-keyring.gpg] \
         https://packages.redis.io/deb noble main" \
         > /etc/apt/sources.list.d/redis.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends redis-server
# un-lock Redis so the API container can talk to it from outside (same tweaks your teacher made)
RUN sed -i 's/^protected-mode yes/protected-mode no/' /etc/redis/redis.conf \
 && sed -i 's/^bind .*/# &/' /etc/redis/redis.conf \
 && sed -i 's/^daemonize no/daemonize no/' /etc/redis/redis.conf

# ── 3.  MongoDB 6.0  (official repo, pinned) ───────────────────────────────
RUN curl -fsSL https://pgp.mongodb.com/server-${MONGO_MAJOR}.asc | gpg --dearmor -o /usr/share/keyrings/mongodb-archive-keyring.gpg \
 && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/mongodb-archive-keyring.gpg] https://repo.mongodb.org/apt/ubuntu $(lsb_release -cs)/mongodb-org/${MONGO_MAJOR} multiverse" \
       > /etc/apt/sources.list.d/mongodb-org-${MONGO_MAJOR}.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
        mongodb-org=${MONGO_VER} \
        mongodb-org-server=${MONGO_VER} \
        mongodb-org-shell=${MONGO_VER} \
        mongodb-org-mongos=${MONGO_VER} \
        mongodb-org-tools=${MONGO_VER}

RUN sed -i 's/^  bindIp:.*$/  bindIp: 0.0.0.0/' /etc/mongod.conf

# ── 4.  Your FastAPI service file  ──────────────────────────────────────────
COPY docker/fastapi.service /etc/systemd/system/fastapi.service
COPY . /app

RUN systemctl enable redis-server.service \
 && systemctl enable mongod.service \
 && systemctl enable fastapi.service

# ── 5.  Enable systemd inside the container (same hack as teacher) ─────────
RUN mkdir -p /run/systemd && echo 'docker' > /run/systemd/container
EXPOSE 80
CMD ["/sbin/init"]
