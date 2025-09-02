
# NoSQL Cloud API with FastAPI, Redis, and MongoDB (Ubuntu 24.04)

This project provides a containerized development environment for interacting with **MongoDB** and **Redis** through a unified **REST API** powered by **FastAPI**.

---

## Access services:

* 🌐 FastAPI → [http://localhost:2250](http://localhost:2250)
* 🍃 MongoDB → mongodb://localhost:27017
* 🧠 Redis → redis\://localhost:6379

⚠️ For MongoDB, always use **double quotes (`"`)** in JSON documents.

---

## 🚀 Features

* 🔧 MongoDB 7.0.5 & Redis 7.0.15 in one container
* 📡 Unified REST API with FastAPI
* 🧪 Run Mongo shell & Redis CLI–style commands over HTTP
* 🐳 Systemd-compatible container (init-based)

---

## 📖 Supported Commands

**MongoDB**

* Insert: `insertOne`, `insertMany`
* Find: `find`, `findOne` with `.limit()`, `.skip()`, `.sort()`, `.count()`
* Update: `updateOne`, `updateMany`
* Delete: `deleteOne`, `deleteMany`
* Aggregate: `aggregate([{...}, {...}])`
* Utility: `countDocuments`, `drop`, `createCollection`

**Redis**

* Keys: `SET`, `GET`, `DEL`, `EXISTS`, `TTL`, `KEYS`
* Lists: `LPUSH`, `RPUSH`, `LPOP`, `RPOP`, `LRANGE`, `LINDEX`, `LINSERT`
* Hashes: `HSET`, `HGET`, `HDEL`
* Sets: `SADD`, `SREM`, `SCARD`
* Sorted Sets: `ZADD`, `ZREM`, `ZINCRBY`

⚠️ Any other commands may not be supported.
For examples, see [`./help.txt`](./help.txt).

---

## 🔑 Authentication

The API requires a **Bearer token** for all requests.

Default token:

```python
TOKEN = "7tVvCQBl0z9jh68QzYX7*KQRBlOiAXNgXn%2"
```

Set it as an environment variable:

```bash
export TOKEN=7tVvCQBl0z9jh68QzYX7*KQRBlOiAXNgXn%2
```

Example usage:

```bash
curl -X POST http://localhost:2250/api/v1/submit \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"database":"redis","commands":"PING"}'
```

You can change the token in `/app/main.py`.

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

* 🌐 FastAPI at `http://localhost:2250/`
* 🍃 MongoDB at `localhost:27017`
* 🧠 Redis at `localhost:6379`

---

## 🧪 Example API Usage

### MongoDB Query

```bash
curl -X POST http://localhost:2250/api/v1/submit \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"database":"mongodb","commands":"db.users.insertOne({\"name\":\"Ann\"})\ndb.users.find({})"}'
```

Response:

```json
{
  "success": true,
  "output": "Inserted document\nFound 1 document(s): [{\"name\": \"Ann\"}]"
}
```

### Redis Query

```bash
curl -X POST http://localhost:2250/api/v1/submit \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"database":"redis","commands":"SET key1 \"hello\"\nGET key1"}'
```

---

### Run Commands from File

```bash
cat <<EOF > mongo_cmds.txt
db.users.insertOne({"name":"Alice"})
db.users.find({})
EOF

curl -X POST http://localhost:2250/api/v1/submit \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"database":"mongodb","commands":"'"$(cat mongo_cmds.txt)"'"}'
```

---

## 🐚 Accessing the Container

```bash
docker exec -it nosql-docker /bin/bash
```

Inside container:

* `redis-cli` → Redis shell
* `mongosh` → MongoDB shell
* Logs & code → `/app`

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
        |   FastAPI   |  <-- REST API (port 2250)
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

### Firewall

Make sure ports **2250, 27017, 6379** are open (Azure NSG / firewall).

### Common errors

* **`MongoDB execution error: Missing closing parenthesis`**
  → Ensure valid JSON (double quotes only).
* **`Redis command not found`**
  → Use uppercase (`SET`, `GET`, `DEL`).

---

