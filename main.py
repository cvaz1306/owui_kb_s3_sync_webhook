import os
from fastapi import FastAPI, Request
from dotenv import load_dotenv
import requests
import uvicorn

# Load environment variables
load_dotenv(".env")

WEBUI_URL = os.getenv("WEBUI_URL", "http://localhost:3000")
TOKEN = os.getenv("TOKEN")
MODEL = os.getenv("MODEL", "llama3.2:latest")
KNOWLEDGE_ID = os.getenv("KNOWLEDGE_ID")

app = FastAPI()

# --- WebUI API helpers ---

def upload_file(file_path):
    """Upload a file to WebUI and return its info dict."""
    url = f'{WEBUI_URL}/api/v1/files/'
    headers = {
        'Authorization': f'Bearer {TOKEN}',
        'Accept': 'application/json'
    }
    # This function is not used in webhook, but included for completeness
    with open(file_path, 'rb') as f:
        files = {'file': f}
        response = requests.post(url, headers=headers, files=files)
    response.raise_for_status()
    return response.json()

def add_file_to_knowledge(knowledge_id, file_id):
    """Associate an uploaded file with a WebUI knowledge base."""
    url = f'{WEBUI_URL}/api/v1/knowledge/{knowledge_id}/file/add'
    headers = {
        'Authorization': f'Bearer {TOKEN}',
        'Content-Type': 'application/json'
    }
    data = {'file_id': file_id}
    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    return response.json()

def remove_file_from_knowledge(knowledge_id, file_id):
    """Remove a file from the WebUI knowledge base."""
    url = f'{WEBUI_URL}/api/v1/knowledge/{knowledge_id}/file/remove'
    headers = {
        'Authorization': f'Bearer {TOKEN}',
        'Content-Type': 'application/json'
    }
    data = {'file_id': file_id}
    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    return response.json()

# --- Webhook endpoint for MinIO notifications ---

@app.post("/minio-events")
async def minio_events(request: Request):
    """Endpoint to receive MinIO object events."""
    data = await request.json()
    if "Records" not in data:
        return {"error": "Missing Records field."}
    for record in data["Records"]:
        event_name = record['eventName']
        object_key = record['s3']['object']['key']
        print(f"Received event {event_name} on object {object_key}")
        # You may need to unquote_plus for object_key if MinIO escapes it.

        if event_name.startswith('s3:ObjectCreated:'):
            # "file_id" is assumed to be the MinIO object key,
            # but if you want full upload, you'll need to download and then call upload_file
            # (You could also record this key in an external DB, etc.)
            print(f"[Created] {object_key}: Adding to KB {KNOWLEDGE_ID}")
            add_file_to_knowledge(KNOWLEDGE_ID, object_key)
        elif event_name.startswith('s3:ObjectRemoved:'):
            print(f"[Deleted] {object_key}: Removing from KB {KNOWLEDGE_ID}")
            remove_file_from_knowledge(KNOWLEDGE_ID, object_key)
    return {"success": True}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5005, reload=True)