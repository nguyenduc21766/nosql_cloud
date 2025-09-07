import threading
from .parsers import parse_redis_command, parse_mongodb_command
from .redis_commands import execute_redis_command
from .mongo_commands import execute_mongodb_command, split_mongo_commands

execution_lock = threading.Lock()

def run_commands(db_name: str, commands: str) -> list[str]:
    output_lines = []
    lines = split_mongo_commands(commands) if db_name == "mongodb" else [ln for ln in commands.strip().split("\n") if ln.strip()]
    for line in lines:
        if not line.strip():
            continue
        if db_name == "redis":
            cmd, args = parse_redis_command(line)
            output_lines.append(execute_redis_command(cmd, args))
        else:
            collection, op, params, chain = parse_mongodb_command(line)
            output_lines.append(execute_mongodb_command(collection, op, params, chain))
    return output_lines
