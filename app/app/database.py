import redis
import pymongo
from fastapi import HTTPException
from logging_config import logger

redis_client = None
mongo_client = None
mongo_db = None

def init_databases():
    global redis_client, mongo_client, mongo_db
    try:
        redis_client = redis.Redis(
            host="localhost",
            port=6379,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
            retry_on_timeout=False
        )
        redis_client.ping()
        logger.info("Redis connection established")
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")
        raise

    try:
        mongo_client = pymongo.MongoClient(
            "mongodb://localhost:27017/",
            serverSelectionTimeoutMS=3000,
            connectTimeoutMS=3000,
            socketTimeoutMS=3000,
            maxPoolSize=10,
            waitQueueTimeoutMS=3000
        )
        mongo_client.admin.command("ping")
        mongo_db = mongo_client["student_db"]
        logger.info("MongoDB connection established")
    except Exception as e:
        logger.error(f"MongoDB connection failed: {e}")
        raise

def check_database_connections():
    try:
        redis_client.ping()
    except Exception as e:
        logger.error(f"Redis connection lost: {e}")
        raise HTTPException(status_code=503, detail="Redis database unavailable")
    try:
        mongo_client.admin.command("ping")
    except Exception as e:
        logger.error(f"MongoDB connection lost: {e}")
        raise HTTPException(status_code=503, detail="MongoDB database unavailable")

def reset_mongodb():
    try:
        for collection_name in mongo_db.list_collection_names():
            mongo_db[collection_name].drop()
        logger.info("MongoDB collections reset")
    except Exception as e:
        logger.error(f"Failed to reset MongoDB: {e}")
        raise

