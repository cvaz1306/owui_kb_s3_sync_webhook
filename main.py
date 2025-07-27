import os
import json
import threading
from fastapi import FastAPI, Request
from dotenv import load_dotenv
import requests
import boto3
import tempfile

# Optionally Redis for id mapping
try:
    import redis
except ImportError:
    redis = None

load_dotenv(".env")

WEBUI_URL   = os.getenv("WEBUI_URL", "http://localhost:8080")
TOKEN       = os.getenv("TOKEN")
MODEL       = os.getenv("MODEL", "llama3.2:latest")
KNOWLEDGE_ID= os.getenv("KNOWLEDGE_ID")

MINIO_ENDPOINT    = os.getenv("MINIO_ENDPOINT")
MINIO_ACCESS_KEY  = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY  = os.getenv("MINIO_SECRET_KEY")
MINIO_BUCKET      = os.getenv("MINIO_BUCKET")
MINIO_SECURE      = os.getenv("MINIO_SECURE", "false").lower() == "true" # string to bool

# Mapping Store config
REDIS_URL      = os.getenv("REDIS_URL")
MAPPING_FILE   = os.getenv("MAPPING_FILE", "mapping.json")

app = FastAPI()

# --- SET UP BOTO3 S3 CLIENT (MinIO) ---
s3 = boto3.client(
    "s3",
    endpoint_url = f"http{'s' if MINIO_SECURE else ''}://{MINIO_ENDPOINT}",
    aws_access_key_id = MINIO_ACCESS_KEY,
    aws_secret_access_key = MINIO_SECRET_KEY,
)

### === MAPPING STORE FOR OBJECT_KEY -> FILE_ID ===

class BaseMapping:
    def set(self, object_key, file_id):
        raise NotImplementedError
    def get(self, object_key):
        raise NotImplementedError
    def remove(self, object_key):
        raise NotImplementedError

class RedisMapping(BaseMapping):
    def __init__(self, url):
        self.r = redis.Redis.from_url(url)
        self.prefix = "minio-webui:"
    def set(self, object_key, file_id):
        self.r.set(f"{self.prefix}{object_key}", file_id)
    def get(self, object_key):
        res = self.r.get(f"{self.prefix}{object_key}")
        if res is not None:
            return res.decode()
        return None
    def remove(self, object_key):
        self.r.delete(f"{self.prefix}{object_key}")

class LocalFileMapping(BaseMapping):
    def __init__(self, file_path):
        self.file_path = file_path
        self.lock = threading.Lock()
        self.cache = None
        self._load()
    def _load(self):
        if not os.path.exists(self.file_path):
            self.cache = {}
            return
        with open(self.file_path, "r") as f:
            try:
                self.cache = json.load(f)
            except Exception:
                self.cache = {}
    def _save(self):
        with open(self.file_path, "w") as f:
            json.dump(self.cache, f)
    def set(self, object_key, file_id):
        with self.lock:
            self.cache[object_key] = file_id
            self._save()
    def get(self, object_key):
        with self.lock:
            return self.cache.get(object_key)
    def remove(self, object_key):
        with self.lock:
            ret = self.cache.pop(object_key, None)
            self._save()
            return ret

def get_mapping_store():
    if REDIS_URL and redis is not None:
        try:
            test = redis.Redis.from_url(REDIS_URL)
            test.ping()
            print("Using Redis for mapping storage.")
            return RedisMapping(REDIS_URL)
        except Exception as e:
            print(f"Redis unavailable: {e}; falling back to local file mapping.")
    else:
        if REDIS_URL and redis is None:
            print("Redis requested but python-redis not installed; using file mapping.")
    print("Using local file for mapping storage.")
    return LocalFileMapping(MAPPING_FILE)

MAPPING = get_mapping_store()

# --- WebUI API helpers ---

def upload_file(file_path:str) -> dict:
    url = f'{WEBUI_URL}/api/v1/files/'
    headers = {
        'Authorization': f'Bearer {TOKEN}',
        'Accept': 'application/json'
    }
    with open(file_path, 'rb') as f:
        files = {'file': f}
        resp = requests.post(url, headers=headers, files=files)
    resp.raise_for_status()
    return resp.json()

def add_file_to_knowledge(knowledge_id:str, file_id:str):
    url = f'{WEBUI_URL}/api/v1/knowledge/{knowledge_id}/file/add'
    headers = {
        'Authorization': f'Bearer {TOKEN}',
        'Content-Type': 'application/json'
    }
    data = {'file_id': file_id}
    resp = requests.post(url, headers=headers, json=data)
    resp.raise_for_status()
    return resp.json()

def remove_file_from_knowledge(knowledge_id:str, file_id:str):
    url = f'{WEBUI_URL}/api/v1/knowledge/{knowledge_id}/file/remove'
    headers = {
        'Authorization': f'Bearer {TOKEN}',
        'Content-Type': 'application/json'
    }
    data = {'file_id': file_id}
    resp = requests.post(url, headers=headers, json=data)
    resp.raise_for_status()
    return resp.json()

def download_minio_object(key:str, bucket:str = None) -> str:
    if bucket is None:
        bucket = MINIO_BUCKET
    fd, temp_path = tempfile.mkstemp(suffix='-' + os.path.basename(key))
    os.close(fd)
    s3.download_file(bucket, key, temp_path)
    return temp_path

# --- Webhook endpoint ---

@app.post("/minio-events")
async def minio_events(request: Request):
    data = await request.json()
    if "Records" not in data:
        return {"error": "Missing Records field."}
    for record in data["Records"]:
        event_name = record['eventName']
        object_key = record['s3']['object']['key']
        bucket_name = record['s3']['bucket']['name']
        print(f"MinIO event: {event_name} {object_key} in {bucket_name}")

        if event_name.startswith('s3:ObjectCreated:'):
            # Step 1: Download from MinIO
            local_path = download_minio_object(object_key, bucket_name)
            try:
                upload_resp = upload_file(local_path)
                file_id = upload_resp['id']
                print(f"[Uploaded] {object_key} as id={file_id}, adding to KB {KNOWLEDGE_ID}...")
                add_file_to_knowledge(KNOWLEDGE_ID, file_id)
                MAPPING.set(object_key, file_id)
            finally:
                os.remove(local_path)
        elif event_name.startswith('s3:ObjectRemoved:'):
            file_id = MAPPING.get(object_key)
            if file_id:
                print(f"[Deleted] {object_key}: Removing id={file_id} from KB {KNOWLEDGE_ID} and mapping store.")
                remove_file_from_knowledge(KNOWLEDGE_ID, file_id)
                MAPPING.remove(object_key)
            else:
                print(f"[Warning] {object_key}: No known file_id mapping for delete event.")

    return {"success": True}

@app.post("/sync-bucket")
def sync_bucket():
    # 1. List all objects in the MinIO bucket
    paginator = s3.get_paginator('list_objects_v2')
    uploaded = []
    already_in_owui = []
    errors = []

    for page in paginator.paginate(Bucket=MINIO_BUCKET):
        for obj in page.get('Contents', []):
            object_key = obj['Key']
            # 2. Check mapping
            existing_file_id = MAPPING.get(object_key)
            if existing_file_id:
                print(f"[SKIP] {object_key} already in WebUI as {existing_file_id}")
                already_in_owui.append(object_key)
                continue
            print(f"[SYNC] {object_key} not in WebUI, uploading...")
            # 3. Download object
            try:
                local_path = download_minio_object(object_key)
                try:
                    # 4. Upload to WebUI
                    upload_resp = upload_file(local_path)
                    file_id = upload_resp['id']
                    add_file_to_knowledge(KNOWLEDGE_ID, file_id)
                    MAPPING.set(object_key, file_id)
                    uploaded.append(object_key)
                    print(f"[OK] Uploaded {object_key} as {file_id}")
                finally:
                    os.remove(local_path)
            except Exception as e:
                print(f"[ERR] Failed {object_key}: {e}")
                errors.append({"object_key":object_key, "error":str(e)})

    return {
        "uploaded": uploaded,
        "already_in_owui": already_in_owui,
        "errors": errors,
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=5005, reload=True)
