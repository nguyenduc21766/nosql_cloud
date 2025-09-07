from fastapi import APIRouter, HTTPException, Header
from config import EXPECTED_TOKEN
from models import Submission
from runner import run_commands, execution_lock
from database import redis_client, reset_mongodb, check_database_connections, mongo_client
from logging_config import logger

router = APIRouter()

@router.get("/")
async def root():
    return {
        "message": "NoSQL CodeRunner API - Supporting Redis and MongoDB",
        "version": "1.0.0",
        "supported_databases": ["redis", "mongodb"]
    }

@router.get("/health")
async def health_check():
    health_status = {"redis": False, "mongodb": False}
    try:
        redis_client.ping(); health_status["redis"] = True
    except Exception as e: logger.error(f"Redis health check failed: {e}")
    try:
        mongo_client.admin.command("ping"); health_status["mongodb"] = True
    except Exception as e: logger.error(f"MongoDB health check failed: {e}")
    return {
        "status": "healthy" if all(health_status.values()) else "degraded",
        "databases": health_status
    }

@router.post("/api/v1/submit")
def submit(submission: Submission, authorization: str = Header(None)):
    if authorization != f"Bearer {EXPECTED_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")
    check_database_connections()
    db_name = submission.database.lower()
    if db_name not in ("redis", "mongodb"):
        raise HTTPException(status_code=400, detail="Supported databases: redis, mongodb")

    with execution_lock:
        try:
            output_lines = run_commands(db_name, submission.commands)
            return {"success": True, "output": "\n".join(output_lines)}
        except Exception as e:
            logger.error(f"Error processing submission: {e}")
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            try:
                if db_name == "redis": redis_client.flushall()
                else: reset_mongodb()
            except Exception as reset_err:
                logger.error(f"Failed to reset {db_name}: {reset_err}")
