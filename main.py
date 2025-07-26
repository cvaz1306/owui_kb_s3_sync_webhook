from fastapi import FastAPI, Request
from pydantic import BaseModel
import uvicorn

app = FastAPI()

knowledge_id = 'your_knowledge_id'

# Add your logic here — these are just placeholders
def add_file_to_knowledge(knowledge_id, object_name):
    print(f"Add to knowledge base: {object_name}")

def remove_file_from_knowledge(knowledge_id, object_name):
    print(f"Remove from knowledge base: {object_name}")

@app.post("/minio-events")
async def minio_events(request: Request):
    data = await request.json()
    for record in data.get('Records', []):
        event_name = record['eventName']
        obj_key = record['s3']['object']['key']
        if event_name.startswith('s3:ObjectCreated:'):
            print(f"[Created] {obj_key}")
            add_file_to_knowledge(knowledge_id, obj_key)
        elif event_name.startswith('s3:ObjectRemoved:'):
            print(f"[Deleted] {obj_key}")
            remove_file_from_knowledge(knowledge_id, obj_key)
    return {"success": True}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5005)