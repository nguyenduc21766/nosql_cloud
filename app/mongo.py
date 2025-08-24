import json
import logging
from bson import ObjectId
from . import db
from .utils import (
    mongo_shell_to_json, split_top_level_json_args, parse_two_params,
    split_mongo_commands, find_matching_paren
)

logger = logging.getLogger(__name__)

def parse_mongodb_command(line: str) -> tuple:
    """Parse a MongoDB command line into (collection | None, base_operation, params_str, chained_methods)."""
    line = line.strip()
    if not line:
        raise ValueError("Empty command")

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



def execute_mongodb_command(collection_name: str, base_operation: str, params_str: str, chained_methods: list) -> str:
    """Execute a MongoDB command and return the result as a string, supporting shell-style JSON, multi-arg ops, and basic chaining."""
    try:
        # For db-level ops, collection_name can be None
        collection = db.mongo_db[collection_name] if collection_name else None


        # ---------- DB-LEVEL HELPERS ----------
        if base_operation == "dropDatabase" and collection_name is None:
            result = db.mongo_db.command("dropDatabase")
            dropped = result.get('dropped', db.mongo_db.name)
            return f"Database dropped: {dropped}"

        if base_operation == "getCollectionNames" and collection_name is None:
            colls = db.mongo_db.list_collection_names()
            return f"Collections: {colls}"

        if base_operation == "getCollectionInfos" and collection_name is None:
            colls = db.mongo_db.list_collections()
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

            db.mongo_db.create_collection(name, **options)
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
