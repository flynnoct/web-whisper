# Whisper HTTP API

GPU-backed FastAPI wrapper around [OpenAI Whisper](https://github.com/openai/whisper).

## Endpoints

- `GET /health`: process, CUDA, loaded-model, and idle-unload state
- `GET /v1/models`: available, cached, and loaded models
- `GET /v1/models/{model}/check-update?verify_checksum=true`: check remote metadata and local model checksum
- `POST /v1/audio/transcriptions`: multipart audio transcription/translation
- `GET /docs`: interactive OpenAPI documentation

The request-level `model` form field defaults to `large-v3`. Loaded models stay in GPU memory for 1800 seconds after their last request, then unload automatically. Model files remain under `./models`.

## 部署

以下步骤以配备 NVIDIA GPU 的 Linux 主机为例。部署前请确认 NVIDIA 驱动可用，且 `nvidia-smi` 能正常显示显卡；首次加载模型时会自动下载模型文件，因此服务器也需要能访问模型下载源。

### 1. 安装系统依赖

Python 3.9+ 和 FFmpeg 是必需的。Debian / Ubuntu 可以执行：

```bash
sudo apt update
sudo apt install -y python3 python3-venv ffmpeg
```

### 2. 创建运行环境

在仓库的 `api` 目录中创建虚拟环境并安装依赖：

```bash
cd api
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

根据机器配置编辑 `.env`。常用配置如下：

```dotenv
WHISPER_DEVICE=cuda
WHISPER_DEFAULT_MODEL=large-v3
WHISPER_MODEL_DIR=./models
WHISPER_IDLE_TIMEOUT=1800
WHISPER_PRELOAD=true
```

若没有 CUDA GPU，请将 `WHISPER_DEVICE` 改为 `cpu`；CPU 转写会明显更慢。模型会缓存到 `WHISPER_MODEL_DIR`，建议为该目录预留足够磁盘空间。

### 3. 试运行并验证

先在前台启动服务：

```bash
.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8001 --workers 1
```

另开一个终端确认健康检查通过：

```bash
curl -fsS http://127.0.0.1:8001/health
```

首次启动且 `WHISPER_PRELOAD=true` 时，会在模型下载及载入完成后才返回健康状态。

### 4. 使用 systemd 常驻运行

仓库提供了用户级 systemd 示例。它假定项目位于 `~/web-whisper/api`，并使用该目录的 `.venv`；如你的部署目录不同，请先修改 [`whisper-api.service`](whisper-api.service) 中的路径。

```bash
mkdir -p ~/.config/systemd/user
cp whisper-api.service ~/.config/systemd/user/whisper-api.service
systemctl --user daemon-reload
systemctl --user enable --now whisper-api
```

常用运维命令：

```bash
systemctl --user status whisper-api
journalctl --user -u whisper-api -f
systemctl --user restart whisper-api
```

如需在用户未登录时持续运行，可由管理员执行 `loginctl enable-linger <用户名>`。服务默认监听 `0.0.0.0:8001`；若不需要局域网访问，建议在 unit 文件中改为 `127.0.0.1`，或通过防火墙、反向代理和认证限制访问。该 API 本身不提供身份认证。

## Example

```bash
curl -sS http://127.0.0.1:8001/v1/audio/transcriptions \
  -F file=@sample.mp3 \
  -F model=large-v3 \
  -F language=zh
```
