# Web Whisper

A lightweight, dependency-free web UI for Whisper with support for:

- Uploading audio or video for transcription
- Selecting a Whisper model from the backend's available models
- Viewing service status, backend URL, CUDA device, and loaded models
- Accessing the Whisper API through a server-side proxy to avoid browser CORS restrictions

## Run

Python 3.9 or later is required.

```bash
python3 server.py
```

Open <http://127.0.0.1:3000> in your browser.

By default, the UI connects to a local Whisper API at `http://127.0.0.1:8001`. To use another backend:

```bash
WHISPER_API_BASE_URL=http://127.0.0.1:8001 python3 server.py
```

Optional environment variables:

| Variable | Default | Description |
| --- | --- | --- |
| `WHISPER_API_BASE_URL` | `http://127.0.0.1:8001` | Whisper API address |
| `HOST` | `0.0.0.0` | Web UI bind address; allows LAN access |
| `PORT` | `3000` | Web UI port |
| `MAX_UPLOAD_BYTES` | `1073741824` | Maximum upload size in bytes (1 GiB by default) |

## Upstream API

- `GET /health`
- `GET /v1/models`
- `POST /v1/audio/transcriptions`

Upload requests forward the `file`, `model`, and optional `language` multipart fields unchanged.
