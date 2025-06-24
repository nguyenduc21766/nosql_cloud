

---

# NoSQL Cloud API with FastAPI, Redis, and MongoDB (Ubuntu 24.04)

This project provides a containerized development environment for interacting with NoSQL databases (MongoDB and Redis) through a unified REST API using FastAPI.

The container is based on **Ubuntu 24.04**, includes **MongoDB 7.0.5**, **Redis 7.0.15**, and exposes a **FastAPI** service for evaluating database commands via HTTP requests.

> ⚠️ This project is intended for development and educational purposes only — not for production deployment.

---

## 🚀 Features

* 🔧 Run MongoDB and Redis services inside a single container
* 📡 Use FastAPI to submit NoSQL commands (Mongo shell or Redis CLI style)
* 🧪 Test endpoints using `curl` or any HTTP client
* 🐳 Systemd-compatible container structure (init-based)

---

## 🧱 Prerequisites

* [Docker](https://www.docker.com/products/docker-desktop/) must be installed
* Port 80 (FastAPI), 27017 (MongoDB), and 6379 (Redis) must be **free** on your system

---

## 🛠️ Setup Instructions

### 1. Clone the Repository

```bash
git clone <your-repo-url>
cd nosql_cloud
```

### 2. Build the Docker Image

```bash
chmod +x build
./build
```

> This will delete any existing image or container named `nosql-docker` and build everything from scratch.

### 3. Run the Container

```bash
chmod +x run
./run
```

This starts a new container and launches:

* 🌐 FastAPI at `http://localhost:80/`
* 🍃 MongoDB at `localhost:27017`
* 🧠 Redis at `localhost:6379`

---

## 🧪 Example API Usage

### MongoDB Query (via REST)

```bash
curl -X POST http://localhost:80/api/v1/submit \
  -H "Authorization: Bearer supersecretkey" \
  -H "Content-Type: application/json" \
  -d '{
        "database":"mongodb",
        "commands":"db.users.insertOne({\"name\":\"Ann\"})\ndb.users.find({})"
      }'
```

### Redis Query (via REST)

```bash
curl -X POST http://localhost:80/api/v1/submit \
  -H "Authorization: Bearer supersecretkey" \
  -H "Content-Type: application/json" \
  -d '{
        "database":"redis",
        "commands":"SET key1 \"hello\"\nGET key1"
      }'
```

---

## 🐚 Accessing the Container

To manually enter the container shell:

```bash
docker exec -it nosql-docker /bin/bash
```

From here, you can run:

* `redis-cli` for Redis
* `mongosh` or `mongo` for MongoDB
* `systemctl status` to inspect services

---

## 📂 Help File

Once inside the container, you can check `/app/help.txt` for a concise guide on using the API and databases.

---

## 🔧 Troubleshooting

* If FastAPI is not reachable, check:

  ```bash
  systemctl status fastapi.service
  ```
* If ports are busy, stop host services:

  ```bash
  sudo systemctl stop mongod
  sudo systemctl stop redis-server
  ```

---

## 📌 Notes

* The container uses `systemd` to manage services.
* Source files for the FastAPI app are stored in `/app`.
