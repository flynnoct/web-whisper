import asyncio
import gc
import hashlib
import logging
import os
import tempfile
import threading
import time
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

import torch
import whisper
from fastapi import FastAPI, File, Form, HTTPException, UploadFile


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("whisper-api")

MODEL_DIR = Path(os.getenv("WHISPER_MODEL_DIR", "./models")).resolve()
DEFAULT_MODEL = os.getenv("WHISPER_DEFAULT_MODEL", "large-v3")
DEVICE = os.getenv("WHISPER_DEVICE", "cuda")
IDLE_TIMEOUT = int(os.getenv("WHISPER_IDLE_TIMEOUT", "1800"))
PRELOAD = os.getenv("WHISPER_PRELOAD", "true").lower() in {"1", "true", "yes"}
CHECK_INTERVAL = max(5, min(60, IDLE_TIMEOUT // 6 or 5))

models: dict[str, whisper.Whisper] = {}
last_used: dict[str, float] = {}
model_lock = threading.RLock()
started_at = time.time()
stop_event = threading.Event()


def _validate_model(name: str) -> str:
    if name not in whisper.available_models():
        raise ValueError(f"Unknown model '{name}'. Available: {', '.join(whisper.available_models())}")
    return name


def _load_model(name: str) -> whisper.Whisper:
    name = _validate_model(name)
    with model_lock:
        if name not in models:
            logger.info("Loading Whisper model %s on %s", name, DEVICE)
            MODEL_DIR.mkdir(parents=True, exist_ok=True)
            models[name] = whisper.load_model(name, device=DEVICE, download_root=str(MODEL_DIR))
            logger.info("Whisper model %s is ready", name)
        last_used[name] = time.monotonic()
        return models[name]


def _unload_model(name: str, *, only_if_idle: bool = False) -> None:
    with model_lock:
        if only_if_idle:
            used_at = last_used.get(name)
            if used_at is None or time.monotonic() - used_at < IDLE_TIMEOUT:
                return
        model = models.pop(name, None)
        last_used.pop(name, None)
        if model is not None:
            logger.info("Unloading idle Whisper model %s", name)
            del model
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()


def _idle_reaper() -> None:
    while not stop_event.wait(CHECK_INTERVAL):
        now = time.monotonic()
        for name, used_at in list(last_used.items()):
            if now - used_at >= IDLE_TIMEOUT:
                # Recheck under the model lock so a request that was active
                # while the reaper waited cannot be unloaded after it finishes.
                _unload_model(name, only_if_idle=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expected_sha256(url: str) -> str | None:
    candidate = url.rstrip("/").split("/")[-2]
    return candidate if len(candidate) == 64 and all(c in "0123456789abcdef" for c in candidate) else None


@asynccontextmanager
async def lifespan(_: FastAPI):
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if DEVICE == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("WHISPER_DEVICE=cuda but CUDA is unavailable")
    if PRELOAD:
        await asyncio.to_thread(_load_model, DEFAULT_MODEL)
    reaper = threading.Thread(target=_idle_reaper, name="model-idle-reaper", daemon=True)
    reaper.start()
    yield
    stop_event.set()
    for name in list(models):
        _unload_model(name)


app = FastAPI(
    title="Whisper HTTP API",
    version="1.0.0",
    description="GPU-backed self-hosted API for OpenAI Whisper.",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, Any]:
    now = time.monotonic()
    with model_lock:
        loaded = list(models)
        model_unload_status = {
            name: {
                "idle_seconds": round(max(0.0, now - last_used[name]), 3),
                "unload_in_seconds": round(max(0.0, IDLE_TIMEOUT - (now - last_used[name])), 3),
            }
            for name in loaded
            if name in last_used
        }
    return {
        "status": "ready",
        "uptime_seconds": round(time.time() - started_at, 3),
        "device": DEVICE,
        "cuda_available": torch.cuda.is_available(),
        "default_model": DEFAULT_MODEL,
        "loaded_models": loaded,
        "model_unload_status": model_unload_status,
        "idle_timeout_seconds": IDLE_TIMEOUT,
    }


@app.get("/v1/models")
def list_models() -> dict[str, Any]:
    return {
        "default": DEFAULT_MODEL,
        "available": whisper.available_models(),
        "loaded": list(models),
        "cached": sorted(path.name for path in MODEL_DIR.glob("*.pt")),
    }


@app.get("/v1/models/{model_name}/check-update")
async def check_model_update(model_name: str, verify_checksum: bool = False) -> dict[str, Any]:
    try:
        _validate_model(model_name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    url = whisper._MODELS[model_name]
    local_path = MODEL_DIR / f"{model_name}.pt"
    expected = _expected_sha256(url)
    local_sha = await asyncio.to_thread(_sha256, local_path) if local_path.exists() and verify_checksum else None
    remote: dict[str, Any] = {"url": url}
    try:
        def head() -> dict[str, Any]:
            request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "whisper-api/1.0"})
            with urllib.request.urlopen(request, timeout=15) as response:
                return {
                    "etag": response.headers.get("ETag"),
                    "last_modified": response.headers.get("Last-Modified"),
                    "content_length": response.headers.get("Content-Length"),
                }
        remote.update(await asyncio.to_thread(head))
    except Exception as exc:
        remote["check_error"] = str(exc)
    return {
        "model": model_name,
        "cached": local_path.exists(),
        "local_path": str(local_path),
        "checksum_verified": local_sha == expected if local_sha and expected else None,
        "local_sha256": local_sha,
        "expected_sha256": expected,
        "update_available": (local_sha != expected) if local_sha and expected else None,
        "remote": remote,
    }


@app.post("/v1/audio/transcriptions")
async def transcribe(
    file: UploadFile = File(...),
    model: str = Form(DEFAULT_MODEL),
    language: str | None = Form(None),
    task: Literal["transcribe", "translate"] = Form("transcribe"),
    prompt: str | None = Form(None),
    temperature: float = Form(0.0),
    word_timestamps: bool = Form(False),
) -> dict[str, Any]:
    try:
        _validate_model(model)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    suffix = Path(file.filename or "audio").suffix
    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp:
            temp_path = temp.name
            while chunk := await file.read(1024 * 1024):
                temp.write(chunk)

        def run() -> dict[str, Any]:
            instance = _load_model(model)
            with model_lock:
                try:
                    return instance.transcribe(
                        temp_path,
                        language=language,
                        task=task,
                        initial_prompt=prompt,
                        temperature=temperature,
                        word_timestamps=word_timestamps,
                        fp16=DEVICE.startswith("cuda"),
                    )
                finally:
                    # Start the idle countdown when this request finishes, even
                    # when decoding fails after the model has been used.
                    last_used[model] = time.monotonic()

        result = await asyncio.to_thread(run)
        return {"model": model, **result}
    except Exception as exc:
        logger.exception("Transcription failed")
        raise HTTPException(status_code=500, detail=f"Transcription failed: {exc}") from exc
    finally:
        await file.close()
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)
