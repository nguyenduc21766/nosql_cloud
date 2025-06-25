from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
import redis
import pymongo
import threading
import json
from typing import Optional, List, Any, Dict, Union
from bson import ObjectId
import logging
import time

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Database clients - Initialize as None, will be set up in startup
redis_client = None
mongo_client = None
mongo_db = None

def init_databases():
    """Initialize database connections with retry logic"""
    global redis_client, mongo_client, mongo_db
    
    # Initialize Redis
    try:
        redis_client = redis.Redis(host="localhost", port=6379, decode_responses=True)
        redis_client.ping()
        logger.info("Redis connection established")
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")
        raise
    
    # Initialize MongoDB with retry
    try:
        mongo_client = pymongo.MongoClient(
            "mongodb://localhost:27017/",
            serverSelectionTimeoutMS=5000,  # 5 second timeout
            connectTimeoutMS=5000
        )
        # Test the connection
        mongo_client.admin.command('ping')
        mongo_db = mongo_client["student_db"]
        logger.info("MongoDB connection established")
    except Exception as e:
        logger.error(f"MongoDB connection failed: {e}")
        raise

# Initialize databases when the module loads
try:
    init_databases()
except Exception as e:
    logger.warning(f"Database initialization failed at startup: {e}")
    # You might want to implement a retry mechanism here

# Lock to allow only one execution at a time
execution_lock = threading.Lock()

# Token for authorization
EXPECTED_TOKEN = "supersecretkey"

# Submission model
class Submission(BaseModel):
    database: str  
    commands: str  

@app.get("/")
async def root():
    return {
        "message": "NoSQL CodeRunner API - Supporting Redis and MongoDB",
        "version": "1.0.0",
        "supported_databases": ["redis", "mongodb"]
    }

@app.get("/health")
async def health_check():
    """Health check endpoint to verify database connections"""
    health_status = {"redis": False, "mongodb": False}
    
    try:
        redis_client.ping()
        health_status["redis"] = True
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")
    
    try:
        mongo_client.admin.command('ping')
        health_status["mongodb"] = True
    except Exception as e:
        logger.error(f"MongoDB connection failed: {e}")
    
    return {
        "status": "healthy" if all(health_status.values()) else "degraded",
        "databases": health_status
    }

def parse_redis_command(line: str) -> tuple:
    """Parse a Redis command line into command and arguments."""
    parts = line.strip().split()
    if not parts:
        raise ValueError("Empty command")
    command = parts[0].upper()
    args = parts[1:]
    return command, args

def parse_mongodb_command(line: str) -> tuple:
    """Parse a MongoDB command line into collection and operation parameters."""
    line = line.strip()
    if not line:
        raise ValueError("Empty command")
    
    # Handle different MongoDB command formats
    if line.startswith("db."):
        # Format: db.collection.operation(params)
        # Remove 'db.' prefix
        remaining = line[3:]  # Remove "db."
        
        # Find the first dot to separate collection from operation
        dot_index = remaining.find('.')
        if dot_index == -1:
            raise ValueError("Invalid MongoDB command format - missing collection.operation")
        
        collection = remaining[:dot_index]
        operation_with_params = remaining[dot_index + 1:]  # Everything after collection.
        
        return collection, operation_with_params
    else:
        raise ValueError("MongoDB commands must start with 'db.'")

def safe_eval_mongodb_params(params_str: str):
    """Safely evaluate MongoDB parameters string to Python objects."""
    if not params_str.strip():
        return []
    
    try:
        # Replace MongoDB-specific syntax with Python syntax
        params_str = params_str.replace("ObjectId(", "ObjectId(")
        
        # Use json.loads for simple cases, eval for more complex ones (with caution)
        # For production, you'd want a more sophisticated parser
        if params_str.startswith("{") or params_str.startswith("["):
            # Try JSON first
            try:
                return [json.loads(params_str)]
            except:
                # Fall back to eval (in real production, use a proper parser)
                return [eval(params_str)]
        else:
            # Multiple parameters separated by commas
            # This is a simplified approach - in production, use a proper parser
            return eval(f"[{params_str}]")
    except Exception as e:
        raise ValueError(f"Invalid MongoDB parameters: {e}")

def execute_redis_command(command: str, args: List[str]) -> str:
    """Execute a Redis command and return the result as a string."""
    
    # SET command
    if command == "SET":
        if len(args) < 2:
            raise ValueError("SET requires at least key and value arguments")
        key = args[0]
        # Check if EX option is provided
        if len(args) >= 4 and args[-2].upper() == "EX":
            try:
                seconds = int(args[-1])
                if seconds <= 0:
                    raise ValueError("EX seconds must be a positive integer")
                value = " ".join(args[1:-2])  # Value is everything between key and EX
                redis_client.set(key, value, ex=seconds)
                return f"Set key '{key}' with value '{value}' and expiration {seconds} seconds"
            except ValueError:
                raise ValueError("EX seconds argument must be a positive integer")
        else:
            # Standard SET without EX
            value = " ".join(args[1:])
            redis_client.set(key, value)
            return f"Set key '{key}' with value '{value}'"
    
    # GET command
    elif command == "GET":
        if len(args) != 1:
            raise ValueError("GET requires exactly one key argument")
        key = args[0]
        value = redis_client.get(key)
        if value is None:
            return f"Key '{key}' not found"
        return f"Value for key '{key}': '{value}'"
    
    # DEL command
    elif command == "DEL":
        if not args:
            raise ValueError("DEL requires at least one key argument")
        deleted = redis_client.delete(*args)
        return f"Deleted {deleted} key(s)"
    
    # EXISTS command
    elif command == "EXISTS":
        if not args:
            raise ValueError("EXISTS requires at least one key argument")
        count = redis_client.exists(*args)
        return f"{count} key(s) exist"
    
    # INCR command
    elif command == "INCR":
        if len(args) != 1:
            raise ValueError("INCR requires exactly one key argument")
        value = redis_client.incr(args[0])
        return f"Incremented key '{args[0]}' to {value}"

    # INCRBY command
    elif command == "INCRBY":
        if len(args) != 2:
            raise ValueError("INCRBY requires key and increment arguments")
        try:
            increment = int(args[1])
        except ValueError:
            raise ValueError("INCRBY increment argument must be an integer")
        value = redis_client.incrby(args[0], increment)
        return f"Incremented key '{args[0]}' by {increment} to {value}"
    
    # DECR command
    elif command == "DECR":
        if len(args) != 1:
            raise ValueError("DECR requires exactly one key argument")
        value = redis_client.decr(args[0])
        return f"Decremented key '{args[0]}' to {value}"

    # DECRBY command
    elif command == "DECRBY":
        if len(args) != 2:
            raise ValueError("DECRBY requires key and decrement arguments")
        try:
            decrement = int(args[1])
        except ValueError:
            raise ValueError("DECRBY decrement argument must be an integer")
        value = redis_client.decrby(args[0], decrement)
        return f"Decremented key '{args[0]}' by {decrement} to {value}"
    
    # EXPIRE command
    elif command == "EXPIRE":
        if len(args) != 2:
            raise ValueError("EXPIRE requires key and seconds arguments")
        try:
            seconds = int(args[1])
            if seconds <= 0:
                raise ValueError("EXPIRE seconds must be a positive integer")
        except ValueError:
            raise ValueError("EXPIRE seconds argument must be a positive integer")
        result = redis_client.expire(args[0], seconds)
        return f"Set expiry on key '{args[0]}' to {seconds} seconds: {'Success' if result else 'Failed'}"
    
    
    # KEYS command
    elif command == "KEYS":
        if len(args) != 1:
            raise ValueError("KEYS requires exactly one pattern argument")
        keys = redis_client.keys(args[0])
        return f"Keys matching pattern '{args[0]}': {keys}"
    
    # FLUSHALL command
    elif command == "FLUSHALL":
        redis_client.flushall()
        return "All keys have been flushed"
    #--------------------------------HASH COMMANDS--------------------------------
    # HSET command (Hash)
    elif command == "HSET":
        if len(args) < 3:
            raise ValueError("HSET requires key, field and value arguments")
        key = args[0]
        field = args[1]
        value = " ".join(args[2:])
        redis_client.hset(key, field, value)
        return f"Set hash field '{field}' in key '{key}' to '{value}'"
    
    # HGET command (Hash)
    elif command == "HGET":
        if len(args) != 2:
            raise ValueError("HGET requires key and field arguments")
        value = redis_client.hget(args[0], args[1])
        if value is None:
            return f"Field '{args[1]}' in key '{args[0]}' not found"
        return f"Value for field '{args[1]}' in key '{args[0]}': '{value}'"
    #--------------------------------LIST COMMANDS--------------------------------
    # LPUSH command (List)
    elif command == "LPUSH":
        if len(args) < 2:
            raise ValueError("LPUSH requires key and at least one value")
        key = args[0]
        values = args[1:]
        count = redis_client.lpush(key, *values)
        return f"Pushed {len(values)} value(s) to list '{key}', new length: {count}"
    
    # RPUSH command (List)
    elif command == "RPUSH":
        if len(args) < 2:
            raise ValueError("RPUSH requires key and at least one value")
        key = args[0]
        values = args[1:]
        count = redis_client.rpush(key, *values)
        return f"Pushed {len(values)} value(s) to list '{key}', new length: {count}"
    
    # LRANGE command (List)
    elif command == "LRANGE":
        if len(args) != 3:
            raise ValueError("LRANGE requires key, start and stop arguments")
        try:
            start = int(args[1])
            stop = int(args[2])
        except ValueError:
            raise ValueError("LRANGE start and stop must be integers")
        values = redis_client.lrange(args[0], start, stop)
        return f"Values in list '{args[0]}' from {start} to {stop}: {values}"

    # LLEN command (List)
    elif command == "LLEN":
        if len(args) != 1:
            raise ValueError("LLEN requires exactly one key argument")
        length = redis_client.llen(args[0])
        return f"Length of list at key '{args[0]}': {length}"

    # LINSERT command (List)
    elif command == "LINSERT":
        if len(args) != 4:
            raise ValueError("LINSERT requires key, AFTER/BEFORE, pivot value, and value arguments")
        key = args[0]
        where = args[1].upper()
        if where not in ["AFTER", "BEFORE"]:
            raise ValueError("LINSERT where argument must be AFTER or BEFORE")
        pivot = args[2]
        value = args[3]
        count = redis_client.linsert(key, where, pivot, value)
        if count == -1:
            return f"No pivot '{pivot}' found in list at key '{key}'"
        return f"Inserted value '{value}' {where.lower()} '{pivot}' in list at key '{key}', new length: {count}"
    
    # LINDEX command (List)
    elif command == "LINDEX":
        if len(args) != 2:
            raise ValueError("LINDEX requires key and index arguments")
        try:
            index = int(args[1])
        except ValueError:
            raise ValueError("LINDEX index must be an integer")
        value = redis_client.lindex(args[0], index)
        if value is None:
            return f"No value found at index {index} in list at key '{args[0]}'"
        return f"Value at index {index} in list at key '{args[0]}': '{value}'"
    # RPOP command 
    elif command == "RPOP":
        if len(args) != 1:
            raise ValueError("RPOP requires exactly one key argument")
        value = redis_client.rpop(args[0])
        if value is None:
            return f"No value popped from list at key '{args[0]}' (list is empty)"
        return f"Popped value '{value}' from right of list at key '{args[0]}'"
    # LPOP command
    elif command == "LPOP":
        if len(args) != 1:
            raise ValueError("LPOP requires exactly one key argument")
        value = redis_client.lpop(args[0])
        if value is None:
            return f"No value popped from list at key '{args[0]}' (list is empty)"
        return f"Popped value '{value}' from left of list at key '{args[0]}'"
    # LTRIM
    elif command == "LTRIM":
        if len(args) != 3:
            raise ValueError("LTRIM requires key, start, and stop arguments")
        try:
            start = int(args[1])
            stop = int(args[2])
        except ValueError:
            raise ValueError("LTRIM start and stop must be integers")
        redis_client.ltrim(args[0], start, stop)
        return f"Trimmed list at key '{args[0]}' to range {start} to {stop}"
    #--------------------------------SET COMMANDS--------------------------------
    # SADD command (Set)
    elif command == "SADD":
        if len(args) < 2:
            raise ValueError("SADD requires key and at least one member")
        key = args[0]
        members = args[1:]
        count = redis_client.sadd(key, *members)
        return f"Added {count} new member(s) to set '{key}'"
    
    # SMEMBERS command (Set)
    elif command == "SMEMBERS":
        if len(args) != 1:
            raise ValueError("SMEMBERS requires exactly one key argument")
        members = redis_client.smembers(args[0])
        return f"Members of set '{args[0]}': {list(members)}"
    
    # WAIT command
    elif command == "WAIT":
        if len(args) != 2:
            raise ValueError("WAIT requires numreplicas and timeout arguments")
        try:
            numreplicas = int(args[0])
            timeout = int(args[1])
        except ValueError:
            raise ValueError("WAIT numreplicas and timeout must be integers")
        num_replicas_acked = redis_client.wait(numreplicas, timeout)
        return f"WAIT: {num_replicas_acked} replicas acknowledged within {timeout}ms"
    
    # TTL command
    elif command == "TTL":
        if len(args) != 1:
            raise ValueError("TTL requires exactly one key argument")
        ttl = redis_client.ttl(args[0])
        if ttl == -2:
            return f"Key '{args[0]}' does not exist"
        elif ttl == -1:
            return f"Key '{args[0]}' has no expiration"
        return f"Time to live for key '{args[0]}': {ttl} seconds"
    
    # PAUSE command
    elif command == "PAUSE":
        if len(args) != 1:
            raise ValueError("Invalid PAUSE syntax. Use: PAUSE <seconds>")
        try:
            delay = int(args[0])
            if delay < 0:
                raise ValueError("PAUSE seconds must be non-negative")
            time.sleep(delay)
            return f"Paused for {delay} seconds"
        except ValueError:
            raise ValueError("Invalid number of seconds")

    # RENAME command
    elif command == "RENAME":
        if len(args) != 2:
            raise ValueError("RENAME requires old key and new key arguments")
        try:
            redis_client.rename(args[0], args[1])
            return f"Renamed key '{args[0]}' to '{args[1]}'"
        except redis.RedisError as e:
            raise ValueError(f"Failed to rename key '{args[0]}' to '{args[1]}': {str(e)}")
    
    # OBJECT command
    elif command == "OBJECT":
        if len(args) < 2 or args[0].upper() != "ENCODING":
            raise ValueError("OBJECT ENCODING requires key argument")
        encoding = redis_client.object("encoding", args[1])
        if encoding is None:
            return f"No encoding found for key '{args[1]}'"
        return f"Encoding for key '{args[1]}': {encoding}"

    # TYPE command
    elif command == "TYPE":
        if len(args) != 1:
            raise ValueError("TYPE requires exactly one key argument")
        key_type = redis_client.type(args[0])
        return f"Type of key '{args[0]}': {key_type}"
    
    # STRLEN command
    elif command == "STRLEN":
        if len(args) != 1:
            raise ValueError("STRLEN requires exactly one key argument")
        length = redis_client.strlen(args[0])
        return f"Length of string at key '{args[0]}': {length}"

    else:
        raise ValueError(f"Unsupported Redis command: '{command}'")

def execute_mongodb_command(collection_name: str, operation_params: str) -> str:
    """Execute a MongoDB command and return the result as a string."""
    
    try:
        # Get the collection
        collection = mongo_db[collection_name]
        
        # Parse the operation and parameters
        operation_params = operation_params.strip()
        
        # Extract operation name and parameters
        if "(" not in operation_params:
            raise ValueError(f"Invalid operation format: {operation_params}")
        
        paren_index = operation_params.find("(")
        operation_name = operation_params[:paren_index]
        
        # Extract parameters (everything between first '(' and last ')')
        params_start = paren_index + 1
        params_end = operation_params.rfind(")")
        
        if params_end == -1:
            raise ValueError("Missing closing parenthesis in operation")
        
        params_str = operation_params[params_start:params_end]
        
        # Handle different operations
        if operation_name == "insertOne":
            if not params_str.strip():
                raise ValueError("insertOne requires a document parameter")
            
            # Parse the JSON document
            try:
                document = json.loads(params_str)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON document: {e}")
            
            result = collection.insert_one(document)
            return f"Inserted document"
        
        elif operation_name == "insertMany":
            if not params_str.strip():
                raise ValueError("insertMany requires an array parameter")
            
            try:
                documents = json.loads(params_str)
                if not isinstance(documents, list):
                    raise ValueError("insertMany requires an array of documents")
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON array: {e}")
            
            result = collection.insert_many(documents)
            return f"Inserted {len(result.inserted_ids)} documents"
        
        elif operation_name == "find":
            if params_str.strip():
                try:
                    query = json.loads(params_str)
                except json.JSONDecodeError as e:
                    raise ValueError(f"Invalid query JSON: {e}")
            else:
                query = {}
            
            results = list(collection.find(query, {"_id": 0}))
            # Convert ObjectId to string for JSON serialization
            for doc in results:
                if '_id' in doc:
                    doc['_id'] = str(doc['_id'])
            
            return f"Found {len(results)} document(s): {results}"
        
        elif operation_name == "findOne":
            if params_str.strip():
                try:
                    query = json.loads(params_str)
                except json.JSONDecodeError as e:
                    raise ValueError(f"Invalid query JSON: {e}")
            else:
                query = {}
            
            result = collection.find_one(query, {"_id": 0})  
            if result:
                if '_id' in result:
                    result['_id'] = str(result['_id'])
                return f"Found document: {result}"
            else:
                return "No document found"
        
        elif operation_name == "updateOne":
            # For updateOne, we expect two JSON objects: filter and update
            try:
                # Split parameters - this is tricky with nested JSON
                # For now, let's use a simple approach
                params = eval(f"[{params_str}]")
                if len(params) != 2:
                    raise ValueError("updateOne requires filter and update parameters")
            except Exception as e:
                raise ValueError(f"Invalid updateOne parameters: {e}")
            
            result = collection.update_one(params[0], params[1])
            return f"Matched {result.matched_count} document(s), modified {result.modified_count}"
        
        elif operation_name == "deleteOne":
            if not params_str.strip():
                query = {}
            else:
                try:
                    query = json.loads(params_str)
                except json.JSONDecodeError as e:
                    raise ValueError(f"Invalid query JSON: {e}")
            
            result = collection.delete_one(query)
            return f"Deleted {result.deleted_count} document(s)"
        
        elif operation_name == "countDocuments":
            if params_str.strip():
                try:
                    query = json.loads(params_str)
                except json.JSONDecodeError as e:
                    raise ValueError(f"Invalid query JSON: {e}")
            else:
                query = {}
            
            count = collection.count_documents(query)
            return f"Document count: {count}"
        
        elif operation_name == "drop":
            collection.drop()
            return f"Collection '{collection_name}' dropped"
        
        else:
            raise ValueError(f"Unsupported MongoDB operation: {operation_name}")
            
    except Exception as e:
        # Re-raise with more context
        raise ValueError(f"MongoDB execution error: {str(e)}")

def reset_mongodb():
    """Reset MongoDB database by dropping all collections."""
    try:
        for collection_name in mongo_db.list_collection_names():
            mongo_db[collection_name].drop()
        logger.info("MongoDB collections reset")
    except Exception as e:
        logger.error(f"Failed to reset MongoDB: {e}")
        raise

@app.post("/api/v1/submit")
def submit(submission: Submission, authorization: Optional[str] = Header(None)):
    # Check auth token
    if authorization != f"Bearer {EXPECTED_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    database = submission.database.lower()
    if database not in ["redis", "mongodb"]:
        raise HTTPException(status_code=400, detail="Supported databases: redis, mongodb")

    with execution_lock:
        try:
            output_lines = []
            lines = submission.commands.strip().split("\n")
            
            for line in lines:
                if not line.strip():
                    continue
                
                if database == "redis":
                    command, args = parse_redis_command(line)
                    result = execute_redis_command(command, args)
                    output_lines.append(result)
                
                elif database == "mongodb":
                    collection, operation_params = parse_mongodb_command(line)
                    result = execute_mongodb_command(collection, operation_params)
                    output_lines.append(result)

            # Reset database after processing
            if database == "redis":
                redis_client.flushall()
            elif database == "mongodb":
                reset_mongodb()
            
            '''Reset the database after each student submission
            Ensure the next student gets a clean database state'''

            return {
                "success": True,
                "output": "\n".join(output_lines)
            }

        except Exception as e:
            logger.error(f"Error processing submission: {e}")
            raise HTTPException(status_code=500, detail=str(e))
