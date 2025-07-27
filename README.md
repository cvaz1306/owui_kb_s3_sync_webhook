# FastAPI MinIO Event Webhook

This project provides a **FastAPI webhook** server that listens for **MinIO bucket notifications** (object created/deleted) in near real time. It is designed for easy Docker deployment and integration with your knowledge base or downstream processing.

## Features

- Listens on port **5005**, `/minio-events` endpoint
- Handles object creation and deletion events from MinIO
- Ready for extension to integrate with your own knowledge base logic
- Dockerized for production or local testing

---

## Usage

### 1. Build and run the Docker container

```bash
docker build -t fastapi-minio-webhook .
docker run -p 5005:5005 fastapi-minio-webhook
```

### 2. Configure MinIO to send notifications

Use [`mc`](https://min.io/docs/minio/linux/reference/minio-mc.html) on the MinIO server/host to add a webhook event:

```bash
mc admin config set myminio notify_webhook:primary endpoint="http://192.168.1.35:5005/minio-events"
mc admin service restart myminio
```

Then, bind the webhook to the bucket you want to monitor:

```bash
mc event add myminio/obsidian-vault arn:minio:sqs::primary:webhook --event "put,delete"
```

- Replace `myminio` with your MinIO alias (check via `mc alias ls`)
- Replace `mybucket` with your bucket name
- Replace `HOST` with your Docker host's IP or `host.docker.internal` (as appropriate)

### 3. Test

Upload or delete files from your MinIO bucket and observe event logs in the FastAPI service.

---

## Custom Logic

Edit `main.py` and add your integration in the `add_file_to_knowledge` and `remove_file_from_knowledge` functions.

---

## Development

- Optional: Edit `requirements.txt` and `main.py` as needed.
- For local development, you can run without Docker:

    ```bash
    pip install -r requirements.txt
    uvicorn main:app --reload --host 0.0.0.0 --port 5005
    ```

---

## Notes

- Make sure your MinIO server can reach the webhook server URL (network/firewall/Docker configuration).
- See the [MinIO Event Notification docs](https://min.io/docs/minio/linux/administration/notifications/bucket/overview.html) for more info.