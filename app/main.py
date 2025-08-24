import logging, threading
from fastapi import FastAPI, HTTPException, Header
from config import EXPECTED_TOKEN
from .schemas import Submission
from .db import init_databases, check_database_connections, reset_mongodb, redis_client
from .mongo import parse_mongodb_command, execute_mongodb_command
from .redis import parse_redis_command, execute_redis_command
from .utils import split_mongo_commands

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
execution_lock = threading.Lock()

# Initialize DBs at import time (same behavior you had)
try:
    init_databases()
except Exception as e:
    logger.warning(f"Database initialization failed at startup: {e}")

@app.get("/")
async def root():
    return {
        "message": "NoSQL CodeRunner API - Supporting Redis and MongoDB",
        "version": "1.0.0",
        "supported_databases": ["redis", "mongodb"]
    }

@app.get("/health")
async def health_check():
    status = {"redis": False, "mongodb": False}
    try:
        from .db import redis_client, mongo_client
        redis_client.ping(); status["redis"] = True
        mongo_client.admin.command('ping'); status["mongodb"] = True
    except Exception:
        pass
    return {
        "status": "healthy" if all(status.values()) else "degraded",
        "databases": status
    }

@app.post("/api/v1/submit")
def submit(submission: Submission, authorization: str = Header(None)):
    if authorization != f"Bearer {API_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    check_database_connections()

    database = submission.database.lower()
    if database not in ["redis", "mongodb"]:
        raise HTTPException(status_code=400, detail="Supported databases: redis, mongodb")

    with execution_lock:
        try:
            output_lines = []
            if database == "mongodb":
                lines = split_mongo_commands(submission.commands)
            else:
                lines = [ln for ln in submission.commands.strip().split("\n") if ln.strip()]

            for line in lines:
                if not line.strip():
                    continue
                if database == "redis":
                    command, args = parse_redis_command(line)
                    result = execute_redis_command(command, args)
                    output_lines.append(result)
                else:
                    collection, op, params, chain = parse_mongodb_command(line)
                    result = execute_mongodb_command(collection, op, params, chain)
                    output_lines.append(result)

            if database == "redis":
                redis_client.flushall()
            else:
                reset_mongodb()

            return {"success": True, "output": "\n".join(output_lines)}

        except Exception as e:
            logger.error(f"Error processing submission: {e}")
            raise HTTPException(status_code=500, detail=str(e))
