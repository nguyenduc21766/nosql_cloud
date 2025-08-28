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
from config import EXPECTED_TOKEN


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Database clients - Initialize as None, will be set up in startup
redis_client = None
mongo_client = None
mongo_db = None

import re 

def mongo_shell_to_json(s: str) -> str:
    """
    Convert common Mongo shell object/array syntax to strict JSON:
      - Normalize single quotes → double quotes for strings
      - Quote unquoted keys (including $operators)
    Pragmatic, not a full JS parser — but robust for typical classroom inputs.
    """
    if not s:
        return s
    # single → double quotes for strings (handles escapes)
    s = re.sub(r"'([^'\\]*(?:\\.[^'\\]*)*)'", r'"\1"', s)
    # quote unquoted keys right after { or ,  (e.g., { key: ... } or , count: ... )
    s = re.sub(r'([{,]\s*)([A-Za-z0-9_\$]+)\s*:', r'\1"\2":', s)
    return s

def split_top_level_json_args(s: str):
    """
    Split 'a, b, c' into ['a', 'b', 'c'] only on commas at top level
    (ignores commas inside strings/braces/brackets/parentheses).
    """
    parts = []
    buf = []
    depth_obj = depth_arr = depth_paren = 0
    in_str = False
    quote = None
    esc = False
    for ch in s:
        buf.append(ch)
        if esc:
            esc = False
            continue
        if ch == '\\':
            esc = True
            continue
        if in_str:
            if ch == quote:
                in_str = False
                quote = None
            continue
        if ch in ('"', "'"):
            in_str = True
            quote = ch
            continue
        if ch == '{': depth_obj += 1
        elif ch == '}': depth_obj -= 1
        elif ch == '[': depth_arr += 1
        elif ch == ']': depth_arr -= 1
        elif ch == '(': depth_paren += 1
        elif ch == ')': depth_paren -= 1

        if ch == ',' and depth_obj == depth_arr == depth_paren == 0:
            parts.append(''.join(buf[:-1]).strip())
            buf = []
    tail = ''.join(buf).strip()
    if tail:
        parts.append(tail)
    return parts

def parse_two_params(params_str: str):
    """
    Parse 0–2 JSON args for find/findOne → (filter_dict, projection_or_None)
    Accepts shell-style and strict JSON.
    """
    if not params_str.strip():
        return {}, None
    parts = split_top_level_json_args(params_str)
    if len(parts) == 1:
        return json.loads(mongo_shell_to_json(parts[0])), None
    if len(parts) == 2:
        return (json.loads(mongo_shell_to_json(parts[0])),
                json.loads(mongo_shell_to_json(parts[1])))
    raise ValueError("At most two arguments supported (filter, projection)")


def init_databases():
    """Initialize database connections with retry logic and short timeouts"""
    global redis_client, mongo_client, mongo_db
    
    # Initialize Redis with shorter timeout
    try:
        redis_client = redis.Redis(
            host="localhost", 
            port=6379, 
            decode_responses=True,
            socket_connect_timeout=3,  # 3 second connection timeout
            socket_timeout=3,          # 3 second socket timeout
            retry_on_timeout=False     # Don't retry on timeout
        )
        # Test connection with timeout
        redis_client.ping()
        logger.info("Redis connection established")
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")
        raise
    
    # Initialize MongoDB with shorter timeouts
    try:
        mongo_client = pymongo.MongoClient(
            "mongodb://localhost:27017/",
            serverSelectionTimeoutMS=3000,  # 3 second timeout (reduced from 5)
            connectTimeoutMS=3000,          # 3 second timeout (reduced from 5)
            socketTimeoutMS=3000,           # 3 second socket timeout
            maxPoolSize=10,                 # Limit connection pool
            waitQueueTimeoutMS=3000         # Queue timeout
        )
        # Test the connection with timeout
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
#EXPECTED_TOKEN = "supersecretkey"

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
    """Health check endpoint to verify database connections with timeout"""
    health_status = {"redis": False, "mongodb": False}
    
    try:
        # Use shorter timeout for health checks
        redis_client.ping()
        health_status["redis"] = True
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
    
    try:
        # MongoDB ping with timeout
        mongo_client.admin.command('ping')
        health_status["mongodb"] = True
    except Exception as e:
        logger.error(f"MongoDB health check failed: {e}")
    
    return {
        "status": "healthy" if all(health_status.values()) else "degraded",
        "databases": health_status
    }

def check_database_connections():
    """Check if database connections are still valid, with timeout protection"""
    try:
        # Quick Redis check with timeout
        redis_client.ping()
    except Exception as e:
        logger.error(f"Redis connection lost: {e}")
        raise HTTPException(status_code=503, detail="Redis database unavailable")
    
    try:
        # Quick MongoDB check with timeout
        mongo_client.admin.command('ping')
    except Exception as e:
        logger.error(f"MongoDB connection lost: {e}")
        raise HTTPException(status_code=503, detail="MongoDB database unavailable")

def parse_redis_command(line: str) -> tuple:
    """Parse a Redis command line into command and arguments."""
    parts = line.strip().split()
    if not parts:
        raise ValueError("Empty command")
    command = parts[0].upper()
    args = parts[1:]
    return command, args


def parse_mongodb_command(line: str) -> tuple:
    """Parse a MongoDB command line into (collection | None, base_operation, params_str, chained_methods)."""
    line = line.strip()
    if not line:
        raise ValueError("Empty command")

    # ---- SPECIAL SHELL KEYWORDS (no 'db.' prefix) ----
    low = line.lower()
    if low.startswith("use "):
        dbname = line.split(None, 1)[1].strip()
        if not dbname:
            raise ValueError("use requires a database name")
        return None, "use_db", dbname, []

    if not line.startswith("db."):
        raise ValueError("MongoDB commands must start with 'db.'")

    remaining = line[3:]  # strip "db."
    # Case A: standard "collection.operation(...)"
    dot_index = remaining.find('.')

    # --- db-level operations like: db.createCollection("name", {...}) ---
    if dot_index == -1:
        # Expect format: <operation>(...)
        if '(' not in remaining:
            raise ValueError("Invalid MongoDB command format - missing parameters")
        paren_index = remaining.find('(')
        base_operation = remaining[:paren_index].strip()
        params_end = remaining.find(')')
        if params_end == -1:
            raise ValueError("Missing closing parenthesis in operation")
        params_str = remaining[paren_index + 1:params_end].strip()
        chained_methods = []  # no chaining for db-level ops
        # collection is None for db-level commands
        return None, base_operation, params_str, chained_methods

    # --- collection-level: collection.operation(...) ---
    collection = remaining[:dot_index]
    operation_part = remaining[dot_index + 1:].strip()

    if '(' not in operation_part:
        raise ValueError("Invalid MongoDB command format - missing parameters")

    paren_index = operation_part.find('(')
    base_operation = operation_part[:paren_index].strip()

    params_end = operation_part.find(')')
    if params_end == -1:
        raise ValueError("Missing closing parenthesis in operation")
    params_str = operation_part[paren_index + 1:params_end].strip()

    # Parse chained methods after the first ')'
    chained_part = operation_part[params_end + 1:].strip()
    chained_methods = []
    current_method = ""
    open_parens = 0

    i = 0
    while i < len(chained_part):
        ch = chained_part[i]
        if ch == '(':
            open_parens += 1
        elif ch == ')':
            open_parens -= 1
            if open_parens == 0 and current_method:
                current_method += ch
                if current_method.startswith('.') and current_method.endswith(')'):
                    chained_methods.append(current_method.strip())
                current_method = ""
        elif open_parens == 0 and ch == '.':
            if current_method and current_method.startswith('.') and current_method.endswith(')'):
                chained_methods.append(current_method.strip())
            current_method = "."
        else:
            current_method += ch
        i += 1

    if current_method and current_method.startswith('.') and current_method.endswith(')'):
        chained_methods.append(current_method.strip())

    return collection, base_operation, params_str, chained_methods


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

    # MSET command
    elif command == "MSET":
        if len(args) < 2 or len(args) % 2 != 0:
            raise ValueError("MSET requires an even number of arguments (key1 value1 key2 value2 ...)")
        
        # Pair up keys and values
        key_value_pairs = {args[i]: args[i + 1] for i in range(0, len(args), 2)}
        try:
            # Use mset to set all key-value pairs atomically
            redis_client.mset(key_value_pairs)
            # Return a confirmation message with all set pairs
            set_pairs = ", ".join([f"{k}: {v}" for k, v in key_value_pairs.items()])
            return f"Set multiple keys: {set_pairs}"
        except redis.RedisError as e:
            raise ValueError(f"Failed to execute MSET: {str(e)}")

    # MGET command
    elif command == "MGET":
        if not args:
            raise ValueError("MGET requires at least one key argument")
        
        try:
            # Retrieve values for all specified keys
            values = redis_client.mget(args)
            # Handle values as strings or None (no decoding needed)
            result = [v if v is not None else None for v in values]
            # Create a mapping of keys to values for the response
            key_value_pairs = {key: value for key, value in zip(args, result)}
            if all(v is None for v in result):
                return f"No values found for keys: {', '.join(args)}"
            return f"Retrieved values: {', '.join([f'{k}: {v}' if v is not None else f'{k}: <not found>' for k, v in key_value_pairs.items()])}"
        except redis.RedisError as e:
            raise ValueError(f"Failed to execute MGET: {str(e)}")

    # DBSIZE command
    elif command == "DBSIZE":
        if args:
            raise ValueError("DBSIZE does not accept arguments")
        
        try:
            # Get the number of keys in the current database
            size = redis_client.dbsize()
            return f"Number of keys in database: {size}"
        except redis.RedisError as e:
            raise ValueError(f"Failed to execute DBSIZE: {str(e)}")

    # SCAN command
    elif command == "SCAN":
        if len(args) < 1 or len(args) > 4:
            raise ValueError("SCAN accepts 1 to 4 arguments: [cursor] [MATCH pattern] [COUNT number]")
        cursor = 0
        match_pattern = None
        count = None
        
        try:
            # Parse mandatory cursor
            cursor = int(args[0]) if args[0].isdigit() else 0
            
            # Parse optional MATCH and COUNT
            for i in range(1, len(args)):
                arg = args[i].upper()
                if arg.startswith("MATCH"):
                    # Join remaining args after MATCH as the pattern
                    match_args = args[i + 1:] if i + 1 < len(args) else []
                    match_pattern = " ".join(match_args) if match_args else None
                    if not match_pattern:
                        raise ValueError("MATCH requires a pattern")
                    break  # MATCH should be the last option if present
                elif arg.startswith("COUNT"):
                    # Extract number after COUNT
                    count_parts = args[i].split(" ", 1)
                    if len(count_parts) != 2 or not count_parts[1].isdigit():
                        raise ValueError("COUNT requires a positive integer")
                    count = int(count_parts[1])
                    if count <= 0:
                        raise ValueError("COUNT must be a positive integer")
            
            # Execute SCAN
            if match_pattern and count:
                cursor, keys = redis_client.scan(cursor, match=match_pattern, count=count)
            elif match_pattern:
                cursor, keys = redis_client.scan(cursor, match=match_pattern)
            elif count:
                cursor, keys = redis_client.scan(cursor, count=count)
            else:
                cursor, keys = redis_client.scan(cursor)
            
            # Keys are already strings due to decode_responses=True
            return f"SCAN cursor: {cursor}, keys: {keys}"
        except redis.RedisError as e:
            raise ValueError(f"Failed to execute SCAN: {str(e)}")
        except ValueError as e:
            raise ValueError(f"Invalid SCAN cursor, MATCH pattern, or COUNT: {str(e)}")
        
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
    # HDEL command
    elif command == "HDEL":
        if len(args) < 2:
            raise ValueError("HDEL requires at least key and one field argument")
        key = args[0]
        fields = args[1:]
        deleted = redis_client.hdel(key, *fields)
        return f"Deleted {deleted} field(s) from hash at key '{key}'"

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
        return f"Added {count} new member(s) to set '{key}': {', '.join(members)}"
    
    # SMEMBERS command (Set)
    elif command == "SMEMBERS":
        if len(args) != 1:
            raise ValueError("SMEMBERS requires exactly one key argument")
        members = redis_client.smembers(args[0])
        return f"Members of set '{args[0]}': {list(members)}"
    # SCARD
    elif command == "SCARD":
        if len(args) != 1:
            raise ValueError("SCARD requires exactly one key argument")
        cardinality = redis_client.scard(args[0])
        return f"Cardinality of set at key '{args[0]}': {cardinality}"    
    # SISMEMBER command
    elif command == "SISMEMBER":
        if len(args) != 2:
            raise ValueError("SISMEMBER requires key and member arguments")
        key = args[0]
        member = args[1]
        exists = redis_client.sismember(key, member)
        return f"Member '{member}' {'is' if exists else 'is not'} in set at key '{key}'"
    # SREM command
    elif command == "SREM":
        if len(args) < 2:
            raise ValueError("SREM requires at least key and one member argument")
        key = args[0]
        members = args[1:]
        removed = redis_client.srem(key, *members)
        return f"Removed {removed} member(s) from set at key '{key}'"
    #--------------------------------------SortedSet----------------------------------------------
    elif command == "ZADD":
        if len(args) < 3 or len(args) % 2 == 0:
            raise ValueError("ZADD requires key, at least one score-member pair (e.g., key score1 member1 score2 member2)")
        key = args[0]
        # Parse score-member pairs: args[1::2] are scores, args[2::2] are members
        scores = [float(arg) for arg in args[1::2]]
        members = args[2::2]
        if len(scores) != len(members):
            raise ValueError("ZADD requires an equal number of scores and members")
        # Prepare dictionary of score-member pairs
        score_member_dict = {member: score for score, member in zip(scores, members)}
        # Add only new members with nx=True
        added = redis_client.zadd(key, score_member_dict, nx=True)
        # List the members that were added (based on input, assuming nx=True ensures only new ones)
        added_members = [member for member in members[:added]] if added > 0 else []
        return f"Added {added} member(s) to sorted set at key '{key}': {added_members}"

    elif command == "ZSCORE":
        if len(args) != 2:
            raise ValueError("ZSCORE requires key and member arguments")
        key = args[0]
        member = args[1]
        score = redis_client.zscore(key, member)
        if score is None:
            return f"No score found for member '{member}' in sorted set at key '{key}'"
        return f"Score for member '{member}' in sorted set at key '{key}': {score}"

    elif command == "ZINCRBY":
        if len(args) != 3:
            raise ValueError("ZINCRBY requires key, increment, and member arguments")
        try:
            increment = float(args[1])
        except ValueError:
            raise ValueError("ZINCRBY increment must be a number")
        key = args[0]
        member = args[2]
        new_score = redis_client.zincrby(key, increment, member)
        return f"Increased score for member '{member}' by {increment} in sorted set at key '{key}' to {new_score}"

    elif command == "ZREM":
        if len(args) < 2:
            raise ValueError("ZREM requires at least key and one member argument")
        key = args[0]
        members = args[1:]
        removed = redis_client.zrem(key, *members)
        return f"Removed {removed} member(s) from sorted set at key '{key}'"

    elif command == "ZRANGE":
        if len(args) < 3:
            raise ValueError("ZRANGE requires key, start, and stop arguments")
        try:
            start = int(args[1])
            stop = int(args[2])
        except ValueError:
            raise ValueError("ZRANGE start and stop must be integers")
        key = args[0]
        with_scores = len(args) > 3 and args[3].upper() == "WITHSCORES"
        if with_scores:
            results = redis_client.zrange(key, start, stop, withscores=True)
            return f"Values in sorted set '{key}' from {start} to {stop} with scores: {[(m.decode() if isinstance(m, bytes) else m, s) for m, s in results]}"
        else:
            results = redis_client.zrange(key, start, stop)
            return f"Values in sorted set '{key}' from {start} to {stop}: {[m.decode() if isinstance(m, bytes) else m for m in results]}"

    #------------------------------------PUBSUB--------------------------------
    elif command == "PUBLISH":
        if len(args) != 2:
            raise ValueError("PUBLISH requires channel and message arguments")
        channel = args[0]
        message = args[1]
        count = redis_client.publish(channel, message)
        return f"Published message '{message}' to channel '{channel}', reached {count} subscriber(s)"


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



def execute_mongodb_command(collection_name: str, base_operation: str, params_str: str, chained_methods: list) -> str:
    """Execute a MongoDB command and return the result as a string, supporting shell-style JSON, multi-arg ops, and basic chaining."""
    try:
        # For db-level ops, collection_name can be None
        collection = mongo_db[collection_name] if collection_name else None

        # ---- Handle "use <dbname>" ----
        if base_operation == "use_db":
            new_name = params_str.strip()
            if not new_name:
                raise ValueError("use requires a database name")
            mongo_db = mongo_client[new_name]  # switch database
            return f"Switched to database: {mongo_db.name}"

        # ---------- DB-LEVEL HELPERS ----------
        if base_operation == "dropDatabase" and collection_name is None:
            result = mongo_db.command("dropDatabase")
            dropped = result.get('dropped', mongo_db.name)
            return f"Database dropped: {dropped}"

        if base_operation == "getCollectionNames" and collection_name is None:
            colls = mongo_db.list_collection_names()
            return f"Collections: {colls}"

        if base_operation == "getCollectionInfos" and collection_name is None:
            colls = mongo_db.list_collections()
            # Convert cursor to list of dicts
            infos = list(colls)
            # make ObjectId printable if present
            for info in infos:
                if 'info' in info and isinstance(info['info'], dict):
                    for k, v in info['info'].items():
                        if isinstance(v, ObjectId):
                            info['info'][k] = str(v)
            return f"Collection infos: {infos}"


        if base_operation == "createCollection":
            if not params_str.strip():
                raise ValueError("createCollection requires a collection name parameter")

            parts = split_top_level_json_args(params_str)
            name = parts[0].strip()

            # Unquote if quoted
            if name.startswith('"') and name.endswith('"'):
                name = json.loads(name)
            elif name.startswith("'") and name.endswith("'"):
                name = name[1:-1]

            options = {}
            if len(parts) > 1:
                options = json.loads(mongo_shell_to_json(parts[1].strip()))

            mongo_db.create_collection(name, **options)
            return f"Collection '{name}' created"

        if base_operation == "adminCommand" and collection_name is None:
            if not params_str.strip():
                raise ValueError("adminCommand requires a parameter object")
            cmd = json.loads(mongo_shell_to_json(params_str))
            result = mongo_client.admin.command(cmd)
            return f"Admin command result: {result}"


        # ---------- INSERT ----------
        if base_operation == "insertOne":
            if not params_str.strip():
                raise ValueError("insertOne requires a document parameter")
            document = json.loads(mongo_shell_to_json(params_str))
            result = collection.insert_one(document)
            return "Inserted document"

        elif base_operation == "insertMany":
            if not params_str.strip():
                raise ValueError("insertMany requires an array parameter")
            documents = json.loads(mongo_shell_to_json(params_str))
            if not isinstance(documents, list):
                raise ValueError("insertMany requires an array of documents")
            result = collection.insert_many(documents)
            return f"Inserted {len(result.inserted_ids)} documents"

        # ---------- FIND ----------
        elif base_operation == "find":
            filter_q, projection = parse_two_params(params_str)
            cursor = collection.find(filter_q, projection or {"_id": 0})

            # Apply chained methods (basic support)
            if chained_methods:
                for method in chained_methods:
                    method = method.strip()
                    if method == ".count()":
                        count = collection.count_documents(filter_q)
                        return f"Document count for query {filter_q}: {count}"
                    elif method.startswith(".limit(") and method.endswith(")"):
                        n = method[len(".limit("):-1].strip()
                        if not n.isdigit():
                            raise ValueError("limit(n) requires an integer")
                        cursor = cursor.limit(int(n))
                    elif method.startswith(".skip(") and method.endswith(")"):
                        n = method[len(".skip("):-1].strip()
                        if not n.isdigit():
                            raise ValueError("skip(n) requires an integer")
                        cursor = cursor.skip(int(n))
                    elif method.startswith(".sort(") and method.endswith(")"):
                        body = method[len(".sort("):-1].strip()
                        sort_spec = json.loads(mongo_shell_to_json(body))
                        if not isinstance(sort_spec, dict) or len(sort_spec) != 1:
                            raise ValueError("sort expects one field: {'field': 1|-1}")
                        field, direction = next(iter(sort_spec.items()))
                        cursor = cursor.sort(field, 1 if int(direction) >= 0 else -1)
                    else:
                        # ignore unknown chains
                        pass

            results = list(cursor)
            for doc in results:
                if '_id' in doc:
                    doc['_id'] = str(doc['_id'])
            return f"Found {len(results)} document(s): {results}"

        elif base_operation == "findOne":
            filter_q, projection = parse_two_params(params_str)
            result = collection.find_one(filter_q, projection or {"_id": 0})
            if result:
                if '_id' in result:
                    result['_id'] = str(result['_id'])
                return f"Found document: {result}"
            return "No document found"

        # ---------- UPDATE ----------
        elif base_operation == "updateOne":
            if not params_str.strip():
                raise ValueError("updateOne requires filter and update parameters")
            parts = split_top_level_json_args(params_str)
            if len(parts) < 2:
                raise ValueError("updateOne requires filter and update parameters")
            filter_query = json.loads(mongo_shell_to_json(parts[0]))
            update_data  = json.loads(mongo_shell_to_json(parts[1]))
            options = json.loads(mongo_shell_to_json(parts[2])) if len(parts) >= 3 else {}
            result = collection.update_one(filter_query, update_data, **options)
            return f"Matched {result.matched_count} document(s), modified {result.modified_count}"

                # ---------- UPDATE MANY ----------
        elif base_operation == "updateMany":
            if not params_str.strip():
                raise ValueError("updateMany requires filter and update parameters")
            parts = split_top_level_json_args(params_str)
            if len(parts) < 2:
                raise ValueError("updateMany requires filter and update parameters")

            filter_query = json.loads(mongo_shell_to_json(parts[0]))
            update_data  = json.loads(mongo_shell_to_json(parts[1]))
            options = json.loads(mongo_shell_to_json(parts[2])) if len(parts) >= 3 else {}

            result = collection.update_many(filter_query, update_data, **options)
            return f"Matched {result.matched_count} document(s), modified {result.modified_count}"


        # ---------- DELETE ----------
        elif base_operation == "deleteOne":
            q = json.loads(mongo_shell_to_json(params_str)) if params_str.strip() else {}
            result = collection.delete_one(q)
            return f"Deleted {result.deleted_count} document(s)"

        elif base_operation == "deleteMany":
            q = json.loads(mongo_shell_to_json(params_str)) if params_str.strip() else {}
            result = collection.delete_many(q)
            return f"Deleted {result.deleted_count} document(s)"

        # ---------- COUNT ----------
        elif base_operation == "countDocuments":
            q = json.loads(mongo_shell_to_json(params_str)) if params_str.strip() else {}
            count = collection.count_documents(q)
            return f"Document count: {count}"

        # ---------- AGGREGATE ----------
        elif base_operation == "aggregate":
            if not params_str.strip():
                raise ValueError("aggregate requires a pipeline array parameter")
            pipeline = json.loads(mongo_shell_to_json(params_str))
            if not isinstance(pipeline, list):
                raise ValueError("aggregate requires an array pipeline")
            cursor = collection.aggregate(pipeline)
            results = list(cursor)
            for doc in results:
                if '_id' in doc and isinstance(doc['_id'], ObjectId):
                    doc['_id'] = str(doc['_id'])
            return f"Aggregated {len(results)} document(s): {results}"

        # ---------- DROP COLLECTION ----------
        elif base_operation == "drop":
            collection.drop()
            return f"Collection '{collection_name}' dropped"

        else:
            raise ValueError(f"Unsupported MongoDB operation: {base_operation}")

    except Exception as e:
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

def split_mongo_commands(src: str):
    """Split MongoDB commands allowing multi-line input.
    Ends a command when (), {}, [] are all balanced and we hit newline/semicolon."""
    cmds = []
    buf = []
    depth_paren = depth_brace = depth_bracket = 0
    in_str = False
    quote = None
    escape = False

    for ch in src:
        buf.append(ch)

        if escape:
            escape = False
            continue

        if ch == '\\':
            escape = True
            continue

        if in_str:
            if ch == quote:
                in_str = False
                quote = None
            continue

        if ch in ("'", '"'):
            in_str = True
            quote = ch
            continue

        if ch == '(':
            depth_paren += 1
        elif ch == ')':
            depth_paren -= 1
        elif ch == '{':
            depth_brace += 1
        elif ch == '}':
            depth_brace -= 1
        elif ch == '[':
            depth_bracket += 1
        elif ch == ']':
            depth_bracket -= 1

        # If all balanced and newline/semicolon appears, end the command
        if ch in ('\n', ';') and depth_paren == depth_brace == depth_bracket == 0:
            chunk = ''.join(buf).strip().rstrip(';')
            if chunk:
                cmds.append(chunk)
            buf = []

    # last chunk
    tail = ''.join(buf).strip().rstrip(';')
    if tail:
        cmds.append(tail)

    return cmds


@app.post("/api/v1/submit")
def submit(submission: Submission, authorization: Optional[str] = Header(None)):
    # Check auth token
    if authorization != f"Bearer {EXPECTED_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Quick connection check with timeout protection
    check_database_connections()

    database = submission.database.lower()
    if database not in ["redis", "mongodb"]:
        raise HTTPException(status_code=400, detail="Supported databases: redis, mongodb")

    with execution_lock:
        try:
            output_lines = []
            #lines = submission.commands.strip().split("\n")
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
                
                elif database == "mongodb":
                    collection, base_operation, params_str, chained_methods = parse_mongodb_command(line)
                    logging.info(f"Parsed command: {line}, Result: (collection={collection}, base_operation={base_operation}, params_str={params_str}, chained_methods={chained_methods})")
                    result = execute_mongodb_command(collection, base_operation, params_str, chained_methods)
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
