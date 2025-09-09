import re, json

def mongo_shell_to_json(s: str) -> str:
    if not s:
        return s
    s = re.sub(r"'([^'\\]*(?:\\.[^'\\]*)*)'", r'"\1"', s)
    s = re.sub(r'([{,]\s*)([A-Za-z0-9_\$]+)\s*:', r'\1"\2":', s)
    return s

def split_top_level_json_args(s: str):
    parts, buf = [], []
    depth_obj = depth_arr = depth_paren = 0
    in_str, quote, esc = False, None, False
    for ch in s:
        buf.append(ch)
        if esc:
            esc = False; continue
        if ch == "\\":
            esc = True; continue
        if in_str:
            if ch == quote: in_str, quote = False, None
            continue
        if ch in ('"', "'"): in_str, quote = True, ch; continue
        if ch == "{": depth_obj += 1
        elif ch == "}": depth_obj -= 1
        elif ch == "[": depth_arr += 1
        elif ch == "]": depth_arr -= 1
        elif ch == "(": depth_paren += 1
        elif ch == ")": depth_paren -= 1
        if ch == "," and depth_obj == depth_arr == depth_paren == 0:
            parts.append("".join(buf[:-1]).strip()); buf = []
    tail = "".join(buf).strip()
    if tail: parts.append(tail)
    return parts

def parse_two_params(params_str: str):
    if not params_str.strip():
        return {}, None
    parts = split_top_level_json_args(params_str)
    if len(parts) == 1:
        return json.loads(mongo_shell_to_json(parts[0])), None
    if len(parts) == 2:
        return (json.loads(mongo_shell_to_json(parts[0])),
                json.loads(mongo_shell_to_json(parts[1])))
    raise ValueError("At most two arguments supported (filter, projection)")

def parse_redis_command(line: str) -> tuple:
    parts = line.strip().split()
    if not parts:
        raise ValueError("Empty command")
    return parts[0].upper(), parts[1:]

def parse_mongodb_command(line: str) -> tuple:
    """Parse a MongoDB command line into (collection | None, base_operation, params_str, chained_methods)."""
    line = line.strip()
    if not line:
        raise ValueError("Empty command")

    # Case: 'use' command (e.g., use myDatabase)
    if line.startswith("use "):
        db_name = line[4:].strip()
        if not db_name:
            raise ValueError("Database name required for 'use' command")
        return None, "use", db_name, []

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
