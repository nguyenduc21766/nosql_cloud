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
    # full function body from your current main.py
    ...
