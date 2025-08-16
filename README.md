---

# NoSQL Cloud API with FastAPI, Redis, and MongoDB (Ubuntu 24.04)

This project provides a containerized development environment for interacting with **MongoDB** and **Redis** through a unified **REST API** powered by **FastAPI**.

It is designed for **learning and development purposes** — not for production.

---

## ⚡ Quickstart

```bash
git clone <your-repo-url>
cd nosql_cloud
./build && ./run
```

Access services:

* 🌐 FastAPI → [http://localhost:80](http://localhost:80)
* 🍃 MongoDB → mongodb://localhost:27017
* 🧠 Redis → redis\://localhost:6379

---


📖 Supported Commands

**MongoDB**

* Insert: insertOne, insertMany

* Find: find, findOne with .limit(), .skip(), .sort(), .count()

* Update: updateOne, updateMany

* Delete: deleteOne, deleteMany

* Aggregate: aggregate([{...}, {...}])

* Utility: countDocuments, drop, createCollection

**Redis**

* Keys: SET, GET, DEL, EXISTS, TTL, KEYS

* Lists: LPUSH, RPUSH, LPOP, RPOP, LRANGE, LINDEX, LINSERT

* Hashes: HSET, HGET, HDEL

* Sets: SADD, SREM, SCARD

* Sorted Sets: ZADD, ZREM, ZINCRBY

⚠️ Any other commands may not be supported.

---

## 🚀 Features

* 🔧 MongoDB 7.0.5 & Redis 7.0.15 in one container
* 📡 Unified REST API with FastAPI
* 🧪 Run Mongo shell & Redis CLI–style commands over HTTP
* 🐳 Systemd-compatible container (init-based)

---

## 🔑 Authentication

The API requires a **Bearer token** in requests.
Default token:

```python
TOKEN = "supersecretkey"
```

You can change this in `/app/config.py`.

---

## 🛠️ Setup Instructions

### 1. Build the Docker Image

```bash
chmod +x build
./build
```

> This removes any existing `nosql-docker` container/image and rebuilds from scratch.

### 2. Run the Container

```bash
chmod +x run
./run
```

This starts:

* 🌐 FastAPI at `http://localhost:80/`
* 🍃 MongoDB at `localhost:27017`
* 🧠 Redis at `localhost:6379`

---

## 🧪 Example API Usage

### MongoDB Query

Request:

```bash
curl -X POST http://localhost:80/api/v1/submit \
  -H "Authorization: Bearer supersecretkey" \
  -H "Content-Type: application/json" \
  -d '{
        "database": "mongodb",
        "commands": "db.users.insertOne({\"name\":\"Ann\"})\ndb.users.find({})"
      }'
```

Response:

```json
{
  "success": true,
  "output": "Inserted document\nFound 1 document(s): [{\"name\": \"Ann\"}]"
}
```

---

### Redis Query

Request:

```bash
curl -X POST http://localhost:80/api/v1/submit \
  -H "Authorization: Bearer supersecretkey" \
  -H "Content-Type: application/json" \
  -d '{
        "database": "redis",
        "commands": "SET key1 \"hello\"\nGET key1"
      }'
```

Response:

```json
{
  "success": true,
  "output": "OK\nValue for key key1: hello"
}
```

---

### Run Commands from File

```bash
cat <<EOF > mongo_cmds.txt
db.users.insertOne({"name":"Alice"})
db.users.find({})
EOF

curl -X POST http://localhost:80/api/v1/submit \
  -H "Authorization: Bearer supersecretkey" \
  -H "Content-Type: application/json" \
  -d '{"database":"mongodb","commands":"'"$(cat mongo_cmds.txt)"'"}'
```

---

## 🐚 Accessing the Container

Enter shell:

```bash
docker exec -it nosql-docker /bin/bash
```

Inside container you can run:

* `redis-cli` for Redis
* `mongosh` for MongoDB
* `systemctl status` to inspect services

---

## 📂 File Locations

* FastAPI app → `/app/main.py`
* MongoDB handler → `/app/main.py`
* Redis handler → `/app/main.py`
* Help file → `/app/help.txt`

---

## 🖼️ Architecture

```
        +-------------+
        |   FastAPI   |  <-- REST API (port 80)
        +------+------+
               |
   +-----------+-----------+
   |                       |
+--v---+             +-----v--+
|MongoDB|:27017      | Redis  |:6379
+-------+            +--------+
```

---

## 🔧 Troubleshooting

### FastAPI not reachable

```bash
systemctl status fastapi.service
```

### MongoDB / Redis ports busy

Stop local services:

```bash
sudo systemctl stop mongod
sudo systemctl stop redis-server
```

### Common errors

* **`MongoDB execution error: Missing closing parenthesis`**
  → Check that your query uses valid JSON-like syntax.
* **`Redis command not found`**
  → Use uppercase (`SET`, `GET`, `DEL`).

---



