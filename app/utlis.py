import json
import re

def mongo_shell_to_json(s: str) -> str:
    """Convert common Mongo shell syntax to strict JSON (single→double quotes, quote keys)."""
    if not s:
        return s
    s = re.sub(r"'([^'\\]*(?:\\.[^'\\]*)*)'", r'"\1"', s)
    s = re.sub(r'([{,]\s*)([A-Za-z0-9_\$]+)\s*:', r'\1"\2":', s)
    return s

def split_top_level_json_args(s: str):
    """Split 'a, b, c' only on top-level commas."""
    parts, buf = [], []
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
    """Parse up to 2 JSON args (filter, projection) for find/findOne."""
    if not params_str.strip():
        return {}, None
    parts = split_top_level_json_args(params_str)
    if len(parts) == 1:
        return json.loads(mongo_shell_to_json(parts[0])), None
    if len(parts) == 2:
        return (json.loads(mongo_shell_to_json(parts[0])),
                json.loads(mongo_shell_to_json(parts[1])))
    raise ValueError("At most two arguments supported (filter, projection)")

def split_mongo_commands(src: str):
    """Split multi-line Mongo commands when (), {}, [] are balanced at newline/semicolon."""
    cmds, buf = [], []
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
        if ch in ('\n', ';') and depth_paren == depth_brace == depth_bracket == 0:
            chunk = ''.join(buf).strip().rstrip(';')
            if chunk:
                cmds.append(chunk)
            buf = []
    tail = ''.join(buf).strip().rstrip(';')
    if tail:
        cmds.append(tail)
    return cmds

def find_matching_paren(s: str, start_idx: int) -> int:
    """Return index of matching ')' for '(' at start_idx; respects strings/brackets/braces."""
    depth_paren = depth_brace = depth_bracket = 0
    in_str = False
    quote = None
    esc = False
    for i in range(start_idx, len(s)):
        ch = s[i]
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
        if ch == '(':
            depth_paren += 1
        elif ch == ')':
            depth_paren -= 1
            if depth_paren == 0:
                return i
        elif ch == '{':
            depth_brace += 1
        elif ch == '}':
            depth_brace -= 1
        elif ch == '[':
            depth_bracket += 1
        elif ch == ']':
            depth_bracket -= 1
    return -1
