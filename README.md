# Web Whisper

An integrated project containing a Whisper transcription API and a lightweight web UI.

```text
.
├── api/   # FastAPI + OpenAI Whisper backend
└── web/   # Dependency-free web UI and reverse proxy
```

## Run the API

By default, the API uses CUDA, preloads `large-v3`, and releases GPU memory after a model has been idle for 30 minutes.

```bash
cd api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app:app --host 0.0.0.0 --port 8001 --workers 1
```

Model files are stored in `api/models/` by default, and that directory is excluded from Git. For server deployments, refer to [`api/whisper-api.service`](api/whisper-api.service) for a user-level systemd service.

## Run the Web UI

```bash
cd web
WHISPER_API_BASE_URL=http://127.0.0.1:8001 python3 server.py
```

The web UI listens on `0.0.0.0:3000` by default. Without `WHISPER_API_BASE_URL`, it connects to a local Whisper API at `http://127.0.0.1:8001`.

See [`api/README.md`](api/README.md) and [`web/README.md`](web/README.md) for detailed documentation for each component.
