const $ = (selector) => document.querySelector(selector);

const elements = {
  badge: $('#status-badge'),
  device: $('#device'),
  backendBaseUrl: $('#backend-base-url'),
  loadedModels: $('#loaded-models'),
  statusMessage: $('#status-message'),
  modelSelect: $('#model-select'),
  form: $('#transcription-form'),
  fileInput: $('#file-input'),
  dropZone: $('#drop-zone'),
  fileLabel: $('#file-label'),
  fileHelp: $('#file-help'),
  recordButton: $('#record-button'),
  recordingHelp: $('#recording-help'),
  submit: $('#submit-button'),
  progress: $('#progress'),
  error: $('#form-error'),
  emptyResult: $('#empty-result'),
  resultText: $('#result-text'),
  resultMeta: $('#result-meta'),
  copy: $('#copy-button'),
};

function formatCountdown(seconds) {
  if (!Number.isFinite(seconds)) return '';
  const total = Math.max(0, Math.ceil(seconds));
  const minutes = Math.floor(total / 60);
  const remainder = total % 60;
  return minutes ? `${minutes}分${remainder}秒` : `${remainder}秒`;
}

async function fetchJSON(url, options) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `请求失败（HTTP ${response.status}）`);
  return data;
}

function setModels(data) {
  const available = data.available_models || data.available || data.models || [];
  const defaultModel = data.default_model || data.default || 'large-v3';
  if (!available.length) return;
  elements.modelSelect.replaceChildren(...available.map((name) => {
    const option = document.createElement('option');
    option.value = option.textContent = name;
    option.selected = name === defaultModel;
    return option;
  }));
}

async function refreshStatus() {
  elements.badge.className = 'status-badge checking';
  elements.badge.lastChild.textContent = '检测中';
  elements.statusMessage.textContent = '';
  const [healthResult, modelsResult] = await Promise.allSettled([
    fetchJSON('/api/health'),
    fetchJSON('/api/models'),
  ]);

  if (healthResult.status === 'rejected') {
    const error = healthResult.reason;
    elements.badge.className = 'status-badge offline';
    elements.badge.lastChild.textContent = '不可用';
    elements.statusMessage.textContent = error.message;
    elements.device.textContent = elements.backendBaseUrl.textContent = elements.loadedModels.textContent = '—';
    return;
  }

  const health = healthResult.value;
  elements.badge.className = 'status-badge online';
  elements.badge.lastChild.textContent = health.status === 'ready' ? '运行中' : health.status;
  elements.device.textContent = `${health.device || '—'}${health.cuda_available === false ? '（CUDA 不可用）' : ''}`;
  elements.backendBaseUrl.textContent = health.backend_base_url || '—';
  elements.backendBaseUrl.title = health.backend_base_url || '';
  elements.loadedModels.textContent = health.loaded_models?.map((name) => {
    const remaining = health.model_unload_status?.[name]?.unload_in_seconds;
    const countdown = formatCountdown(Number(remaining));
    return countdown ? `${name}（${countdown}后卸载）` : name;
  }).join(', ') || '无';
  if (modelsResult.status === 'fulfilled') setModels(modelsResult.value);
}

let mediaRecorder;
let recordingStream;
let recordedChunks = [];
let recordingStartedAt;
let recordingTimer;

function formatRecordingTime(milliseconds) {
  const totalSeconds = Math.floor(milliseconds / 1000);
  return `${String(Math.floor(totalSeconds / 60)).padStart(2, '0')}:${String(totalSeconds % 60).padStart(2, '0')}`;
}

function stopRecordingStream() {
  recordingStream?.getTracks().forEach((track) => track.stop());
  recordingStream = undefined;
}

function setRecordingIdle(message = '使用浏览器麦克风录制后即可转写') {
  clearInterval(recordingTimer);
  elements.recordButton.textContent = '开始录音';
  elements.recordButton.classList.remove('recording');
  elements.recordButton.setAttribute('aria-pressed', 'false');
  elements.recordingHelp.textContent = message;
}

async function startRecording() {
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    elements.error.textContent = '当前浏览器不支持录音，请选择音频文件上传。';
    return;
  }
  elements.error.textContent = '';
  try {
    recordingStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    recordedChunks = [];
    const mimeType = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'].find((type) => MediaRecorder.isTypeSupported(type));
    mediaRecorder = new MediaRecorder(recordingStream, mimeType ? { mimeType } : undefined);
    mediaRecorder.addEventListener('dataavailable', (event) => {
      if (event.data.size) recordedChunks.push(event.data);
    });
    mediaRecorder.addEventListener('stop', () => {
      const type = mediaRecorder.mimeType || 'audio/webm';
      const extension = type.includes('mp4') ? 'm4a' : 'webm';
      const recording = new File([new Blob(recordedChunks, { type })], `录音-${new Date().toISOString().replace(/[:.]/g, '-')}.${extension}`, { type });
      const transfer = new DataTransfer();
      transfer.items.add(recording);
      elements.fileInput.files = transfer.files;
      showFile(recording);
      stopRecordingStream();
      setRecordingIdle('录音已准备好，可以开始转写');
    });
    mediaRecorder.start();
    recordingStartedAt = performance.now();
    elements.recordButton.textContent = '结束录音';
    elements.recordButton.classList.add('recording');
    elements.recordButton.setAttribute('aria-pressed', 'true');
    recordingTimer = setInterval(() => {
      elements.recordingHelp.textContent = `正在录音 ${formatRecordingTime(performance.now() - recordingStartedAt)}`;
    }, 250);
  } catch (error) {
    stopRecordingStream();
    setRecordingIdle();
    elements.error.textContent = error.name === 'NotAllowedError' ? '未获得麦克风权限，请允许后重试。' : '无法启动录音，请检查麦克风是否可用。';
  }
}

function toggleRecording() {
  if (mediaRecorder?.state === 'recording') mediaRecorder.stop();
  else startRecording();
}

function showFile(file) {
  if (!file) return;
  elements.fileLabel.textContent = file.name;
  elements.fileHelp.textContent = `${(file.size / 1024 / 1024).toFixed(1)} MB`;
}

elements.fileInput.addEventListener('change', () => showFile(elements.fileInput.files[0]));
elements.recordButton.addEventListener('click', toggleRecording);
['dragenter', 'dragover'].forEach((eventName) => elements.dropZone.addEventListener(eventName, (event) => {
  event.preventDefault();
  elements.dropZone.classList.add('dragging');
}));
['dragleave', 'drop'].forEach((eventName) => elements.dropZone.addEventListener(eventName, (event) => {
  event.preventDefault();
  elements.dropZone.classList.remove('dragging');
}));
elements.dropZone.addEventListener('drop', (event) => {
  const file = event.dataTransfer.files[0];
  if (!file) return;
  const transfer = new DataTransfer();
  transfer.items.add(file);
  elements.fileInput.files = transfer.files;
  showFile(file);
});

elements.form.addEventListener('submit', async (event) => {
  event.preventDefault();
  elements.error.textContent = '';
  if (!elements.fileInput.files.length) {
    elements.error.textContent = '请先选择一个音频或视频文件。';
    return;
  }
  elements.submit.disabled = true;
  elements.progress.hidden = false;
  const startedAt = performance.now();
  try {
    const result = await fetchJSON('/api/transcriptions', { method: 'POST', body: new FormData(elements.form) });
    elements.emptyResult.hidden = true;
    elements.resultText.hidden = false;
    elements.resultText.value = result.text || '';
    elements.resultMeta.hidden = false;
    elements.resultMeta.textContent = `模型 ${result.model || elements.modelSelect.value} · 语言 ${result.language || '自动'} · 用时 ${((performance.now() - startedAt) / 1000).toFixed(1)} 秒`;
    elements.copy.disabled = !result.text;
  } catch (error) {
    elements.error.textContent = error.message;
  } finally {
    elements.submit.disabled = false;
    elements.progress.hidden = true;
    refreshStatus();
  }
});

elements.copy.addEventListener('click', async () => {
  await navigator.clipboard.writeText(elements.resultText.value);
  elements.copy.textContent = '已复制';
  setTimeout(() => { elements.copy.textContent = '复制文字'; }, 1500);
});

$('#refresh-status').addEventListener('click', refreshStatus);
refreshStatus();
