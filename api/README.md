# Whisper HTTP API

GPU-backed FastAPI wrapper around [OpenAI Whisper](https://github.com/openai/whisper).

## Endpoints

- `GET /health`: process, CUDA, loaded-model, and idle-unload state
- `GET /v1/models`: available, cached, and loaded models
- `GET /v1/models/{model}/check-update?verify_checksum=true`: check remote metadata and local model checksum
- `POST /v1/audio/transcriptions`: multipart audio transcription/translation
- `GET /docs`: interactive OpenAPI documentation

The request-level `model` form field defaults to `large-v3`. Loaded models stay in GPU memory for 1800 seconds after their last request, then unload automatically. Model files remain under `./models`.

## Deployment

The following steps target a Linux host with an NVIDIA GPU. Before deploying, make sure the NVIDIA driver is installed and `nvidia-smi` can detect the GPU. Model files are downloaded automatically on first load, so the server also needs access to the model download source.

### 1. Install system dependencies

Python 3.9+ and FFmpeg are required. On Debian or Ubuntu, run:

```bash
sudo apt update
sudo apt install -y python3 python3-venv ffmpeg
```

### 2. Create the runtime environment

Create a virtual environment and install dependencies in the repository's `api` directory:

```bash
cd api
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` for your machine. Common settings are:

```dotenv
WHISPER_DEVICE=cuda
WHISPER_DEFAULT_MODEL=large-v3
WHISPER_MODEL_DIR=./models
WHISPER_IDLE_TIMEOUT=1800
WHISPER_PRELOAD=true
```

If no CUDA GPU is available, set `WHISPER_DEVICE` to `cpu`; transcription will be substantially slower. Models are cached in `WHISPER_MODEL_DIR`, so reserve sufficient disk space for that directory.

### 3. Run and verify

First, start the service in the foreground:

```bash
.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8001 --workers 1
```

In another terminal, confirm that the health check succeeds:

```bash
curl -fsS http://127.0.0.1:8001/health
```

On the first startup with `WHISPER_PRELOAD=true`, the health endpoint will not be ready until the model download and loading have finished.

### 4. Run continuously with systemd

The repository includes a user-level systemd example. It assumes the project is located at `~/web-whisper/api` and uses the `.venv` in that directory. If your deployment directory differs, update the paths in [`whisper-api.service`](whisper-api.service) first.

```bash
mkdir -p ~/.config/systemd/user
cp whisper-api.service ~/.config/systemd/user/whisper-api.service
systemctl --user daemon-reload
systemctl --user enable --now whisper-api
```

Common operations:

```bash
systemctl --user status whisper-api
journalctl --user -u whisper-api -f
systemctl --user restart whisper-api
```

To keep the service running while its user is logged out, an administrator can run `loginctl enable-linger <username>`. The service listens on `0.0.0.0:8001` by default. If LAN access is not needed, change it to `127.0.0.1` in the unit file, or restrict access through a firewall, reverse proxy, and authentication. The API itself does not provide authentication.

## Example

```bash
curl -sS http://127.0.0.1:8001/v1/audio/transcriptions \
  -F file=@sample.mp3 \
  -F model=large-v3 \
  -F language=zh
```
