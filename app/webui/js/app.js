/* MPWE 前端核心逻辑：状态管理、选项加载、生成与历史。
   画质增强 / LoRA 面板的专属逻辑分别在 js/features/quality.js 与 js/features/loras.js。 */
"use strict";

const $ = (id) => document.getElementById(id);

const state = {
  comfyuiConnected: false,
  pollingJobId: null,
  optionsLoaded: false,
  currentUser: null,
  turnstileSiteKey: "",
  turnstileToken: "",
  turnstileWidgetId: null,
  billing: { signup_bonus: {}, free_recharge: {} },
  diffusionModels: [],
  upscaleModels: [],
  loraModels: [],
  diffusionPresets: {},
  checkpointPresets: {},
  agentModels: {},
  currentQuality: {},
  loraPresets: {},
  lastImage: null,
  historyImages: {},
  currentJobId: null,
  currentJobImages: [],
  currentImageIndex: 0,
  lightboxZoom: 1,
  lightboxPanX: 0,
  lightboxPanY: 0,
  lightboxDrag: null,
  suppressCloseUntil: 0,
};

/* ---------------- 健康检查 ---------------- */
async function fetchJSON(url, options) {
  const opts = options || {};
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), opts.timeout || 15000);
  let resp;
  try {
    resp = await fetch(url, { ...opts, signal: ctrl.signal });
  } catch (err) {
    if (err.name === "AbortError") {
      throw new Error("请求超时（15s）");
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const data = await resp.json();
      detail = data.detail || detail;
    } catch (_) { /* ignore */ }
    throw new Error(`${resp.status} ${detail}`);
  }
  return resp.json();
}

async function refreshHealth() {
  try {
    const data = await fetchJSON("/mpwe/health");
    setDot("backend-dot", true);
    setDot("comfyui-dot", data.comfyui_connected);
    setStatusDetail(data.comfyui_connected ? "" : "绘画GPU服务器离线");
    state.comfyuiConnected = data.comfyui_connected;
    pollQueueStatus();
    $("generate-btn").disabled = !canGenerate();
    if (data.comfyui_connected && !state.optionsLoaded) {
      state.optionsLoaded = true;
      loadOptions();
    } else if (!data.comfyui_connected) {
      state.optionsLoaded = false;
    }
  } catch (err) {
    setDot("backend-dot", false);
    setDot("comfyui-dot", false);
    $("generate-btn").disabled = true;
    setStatusDetail("健康检查失败：" + err.message);
  }
}

/* ---------------- GPU 队列状态 ---------------- */
async function pollQueueStatus() {
  try {
    const q = await fetchJSON("/mpwe/queue");
    const parts = [];
    if (q.running > 0) parts.push(`运行中 ${q.running}`);
    if (q.queued > 0) parts.push(`排队 ${q.queued}`);
    parts.push(`空闲显存 ${(q.free_mb / 1024).toFixed(1)}G`);
    $("queue-meta").textContent = parts.length ? "GPU 队列 · " + parts.join(" · ") : "";
  } catch (_) {
    /* 队列接口失败不影响主流程 */
  }
}

function canGenerate() {
  return state.comfyuiConnected && !!state.currentUser;
}

function setDot(id, online) {
  const el = $(id);
  el.className = "dot " + (online ? "online" : "offline");
}

function setStatusDetail(text) {
  const el = $("status-detail");
  if (!el) return;
  el.textContent = text;
  el.className = "status-detail" + (text ? " warn" : "");
}

/* ---------------- 选项加载 ---------------- */
async function loadOptions() {
  try {
    const [models, samplers, schedulers, workflows, diffusion, upscales, loras, presets, ckptPresets] = await Promise.all([
      fetchJSON("/mpwe/comfyui/models?category=checkpoints"),
      fetchJSON("/mpwe/comfyui/samplers"),
      fetchJSON("/mpwe/comfyui/schedulers"),
      fetchJSON("/mpwe/comfyui/workflows"),
      fetchJSON("/mpwe/comfyui/models?category=diffusion_models"),
      fetchJSON("/mpwe/comfyui/models?category=upscale_models"),
      fetchJSON("/mpwe/comfyui/models?category=loras"),
      fetchJSON("/mpwe/comfyui/diffusion_presets"),
      fetchJSON("/mpwe/comfyui/checkpoint_presets"),
    ]);
    fillSelect($("checkpoint"), models.models);
    if (models.models.includes("one obsession_v14.safetensors")) {
      $("checkpoint").value = "one obsession_v14.safetensors";
    }
    fillSelect($("sampler"), samplers.samplers);
    fillSelect($("scheduler"), schedulers.schedulers);
    fillSelect($("unet"), diffusion.models);
    state.diffusionModels = diffusion.models || [];
    state.upscaleModels = upscales.models || [];
    state.loraModels = loras.models || [];
    state.diffusionPresets = presets.presets || {};
    state.checkpointPresets = ckptPresets.presets || {};
    fillSelect($("upscale_model"), state.upscaleModels);
    applyModelPreset();
    if (workflows.workflows.length === 0) {
      showError("后端没有注册任何工作流");
    }
  } catch (err) {
    fillSelect($("checkpoint"), []);
    fillSelect($("sampler"), []);
    fillSelect($("scheduler"), []);
    fillSelect($("unet"), []);
    showError("加载选项失败：" + err.message);
  }
}

function fillSelect(select, items) {
  select.innerHTML = "";
  if (!items || items.length === 0) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "（未连接绘画GPU服务器）";
    select.appendChild(opt);
    return;
  }
  for (const item of items) {
    const opt = document.createElement("option");
    opt.value = item;
    opt.textContent = item;
    select.appendChild(opt);
  }
}

/* ---------------- 模型类型与预设 ---------------- */
function applyModelPreset() {
  const type = $("model_type").value;
  const isCheckpoint = type === "checkpoint";
  $("checkpoint-fields").classList.toggle("hidden", !isCheckpoint);
  $("diffusion-fields").classList.toggle("hidden", isCheckpoint);

  if (isCheckpoint) {
    applyCheckpointPreset();
    updateAgentAvailability();
    return;
  }

  const pick = (list, keyword, fallback) =>
    list.find((m) => m.includes(keyword)) || fallback || list[0] || "";

  if (type === "z_image") {
    $("unet").value = pick(state.diffusionModels, "z_image_turbo", "");
  } else if (type === "anima") {
    $("unet").value = pick(state.diffusionModels, "anima", "");
  }
  applyDiffusionPreset();
  updateAgentAvailability();
}

function applyDiffusionPreset() {
  const unet = $("unet").value;
  const preset = state.diffusionPresets[unet];
  if (!preset) {
    $("model-hint").textContent = "该模型暂无官方预设，请联系维护者补充 presets.py。";
    renderResolutionPresets(null);
    updateAgentAvailability();
    return;
  }
  if (preset.steps != null) $("steps").value = preset.steps;
  if (preset.cfg != null) $("cfg").value = preset.cfg;
  if (preset.sampler) $("sampler").value = preset.sampler;
  if (preset.scheduler) $("scheduler").value = preset.scheduler;
  if (preset.width) $("width").value = preset.width;
  if (preset.height) $("height").value = preset.height;
  if (preset.clip_skip != null) $("clip_skip").value = preset.clip_skip;
  applyQualityPreset(preset.quality || {});
  applyLoraPreset(preset.loras || []);
  renderResolutionPresets(preset);
  $("model-hint").textContent = "已按官方预设自动配置：" + (preset.note || "");
  updateAgentAvailability();
}

function applyCheckpointPreset() {
  const ckpt = $("checkpoint").value;
  const preset = state.checkpointPresets[ckpt];
  if (!preset) {
    $("checkpoint-hint").textContent = "";
    renderResolutionPresets(null);
    updateAgentAvailability();
    return;
  }
  if (preset.steps != null) $("steps").value = preset.steps;
  if (preset.cfg != null) $("cfg").value = preset.cfg;
  if (preset.sampler) $("sampler").value = preset.sampler;
  if (preset.scheduler) $("scheduler").value = preset.scheduler;
  if (preset.width) $("width").value = preset.width;
  if (preset.height) $("height").value = preset.height;
  if (preset.clip_skip != null) $("clip_skip").value = preset.clip_skip;
  applyQualityPreset(preset.quality || {});
  applyLoraPreset(preset.loras || []);
  renderResolutionPresets(preset);
  $("checkpoint-hint").textContent = "已按官方预设自动配置：" + (preset.note || "");
  updateAgentAvailability();
}

/* ---------------- 分辨率预设 ---------------- */
function currentPreset() {
  const type = $("model_type").value;
  return type === "checkpoint"
    ? state.checkpointPresets[$("checkpoint").value]
    : state.diffusionPresets[$("unet").value];
}

function renderResolutionPresets(preset) {
  const wrap = $("res-presets");
  const list = $("res-preset-list");
  const presets = (preset && preset.resolution_presets) || [];
  list.innerHTML = "";
  if (!presets.length) {
    wrap.hidden = true;
    return;
  }
  presets.forEach((p, i) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "res-preset";
    btn.dataset.index = String(i);
    const name = document.createElement("span");
    name.className = "res-preset-name";
    name.textContent = p.name || `${p.width} × ${p.height}`;
    const size = document.createElement("span");
    size.className = "res-preset-size";
    size.textContent = `${p.width} × ${p.height}`;
    btn.appendChild(name);
    btn.appendChild(size);
    if (p.note) btn.title = p.note;
    btn.addEventListener("click", () => {
      $("width").value = p.width;
      $("height").value = p.height;
      syncResolutionPresetActive();
    });
    list.appendChild(btn);
  });
  wrap.hidden = false;
  syncResolutionPresetActive();
}

function syncResolutionPresetActive() {
  const w = parseInt($("width").value, 10);
  const h = parseInt($("height").value, 10);
  const presets = (currentPreset() && currentPreset().resolution_presets) || [];
  [...$("res-preset-list").children].forEach((btn) => {
    const p = presets[Number(btn.dataset.index)];
    btn.classList.toggle(
      "active",
      !!p && parseInt(p.width, 10) === w && parseInt(p.height, 10) === h
    );
  });
}

/* ---------------- 生成 ---------------- */
function collectParams(forQualityPass) {
  const type = $("model_type").value;
  const workflow = forQualityPass
    ? "quality_pass"
    : type === "z_image" ? "z_image_txt2img" : type === "anima" ? "anima_txt2img" : "txt2img";
  const params = {
    workflow,
    checkpoint: type === "checkpoint" ? $("checkpoint").value : "",
    unet_name: type === "checkpoint" ? null : $("unet").value,
    clip_name: null,
    clip_type: null,
    vae_name: null,
    model_shift: null,
    prompt: $("prompt").value,
    negative_prompt: $("negative_prompt").value,
    width: parseInt($("width").value, 10),
    height: parseInt($("height").value, 10),
    steps: parseInt($("steps").value, 10),
    cfg: parseFloat($("cfg").value),
    sampler: $("sampler").value,
    scheduler: $("scheduler").value,
    seed: parseInt($("seed").value, 10),
    batch_size: parseInt($("batch_size").value, 10),
    filename_prefix: $("filename_prefix").value || "MPWE",
    clip_skip: parseInt($("clip_skip").value || "0", 10),
    hires_fix: forQualityPass ? $("hires_fix").checked : false,
    upscale_model: $("upscale_model").value || "",
    hires_denoise: parseFloat($("hires_denoise").value),
    hires_steps: parseInt($("hires_steps").value, 10),
    hires_cfg: (state.currentQuality.hires && state.currentQuality.hires.cfg) || 0,
    face_detailer: forQualityPass ? $("face_detailer").checked : false,
    face_detector: $("face_detector").value,
    face_threshold: (state.currentQuality.face_detailer && state.currentQuality.face_detailer.threshold) || 0.5,
    face_denoise: parseFloat($("face_denoise").value),
    face_steps: parseInt($("face_steps").value, 10),
    face_cfg: (state.currentQuality.face_detailer && state.currentQuality.face_detailer.cfg) || 5.0,
    face_guide_size: (state.currentQuality.face_detailer && state.currentQuality.face_detailer.guide_size) || 512,
    face_max_size: (state.currentQuality.face_detailer && state.currentQuality.face_detailer.max_size) || 1024,
    loras: collectLoraParams(),
  };
  if (forQualityPass) {
    params.image_filename = state.lastImage ? state.lastImage.filename : "";
    params.image_subfolder = state.lastImage ? state.lastImage.subfolder || "" : "";
    params.image_type = state.lastImage ? state.lastImage.type || "output" : "output";
  }
  return params;
}

async function generate() {
  hideError();
  if (!state.comfyuiConnected) {
    showError("绘画GPU服务器未连接，请先启动绘画GPU服务器");
    return;
  }
  const params = collectParams(false);
  await submitJob(params);
}

async function submitJob(params) {
  hideError();
  $("generate-btn").disabled = true;
  $("generate-btn").classList.add("busy");
  $("quality-btn").disabled = true;
  $("job-status").textContent = "提交中…";
  $("progress-bar").style.width = "0%";
  $("progress-text").textContent = "提交中…";
  $("progress-wrap").hidden = false;
  $("cancel-btn").hidden = true;

  try {
    const job = await fetchJSON("/mpwe/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    });
    state.pollingJobId = job.id;
    $("cancel-btn").hidden = false;
    pollJob(job.id);
  } catch (err) {
    $("generate-btn").disabled = !canGenerate();
    $("generate-btn").classList.remove("busy");
    $("quality-btn").disabled = false;
    $("job-status").textContent = "提交失败";
    $("progress-wrap").hidden = true;
    showError("提交任务失败：" + err.message);
  }
}

async function pollJob(jobId) {
  try {
    const job = await fetchJSON(`/mpwe/jobs/${jobId}`);
    renderJobStatus(job);
    if (job.status === "queued" || job.status === "running") {
      setTimeout(() => pollJob(jobId), 1500);
      return;
    }
    state.pollingJobId = null;
    $("generate-btn").disabled = !canGenerate();
    $("generate-btn").classList.remove("busy");
    $("quality-btn").disabled = false;
    $("cancel-btn").hidden = true;

    if (job.status === "done" && job.images.length > 0) {
      state.lastImage = job.images[0];
      $("quality-panel").hidden = false;
      setViewer(job.id, job.images, 0);
    } else if (job.status === "canceled") {
      $("job-status").textContent = "已取消";
      $("progress-wrap").hidden = true;
    } else if (job.status === "error") {
      showError("生成失败：" + (job.error || "未知错误"));
    } else {
      showError("任务未产生图片");
    }
    loadHistory();
    refreshMe();
  } catch (err) {
    state.pollingJobId = null;
    $("generate-btn").disabled = !canGenerate();
    $("generate-btn").classList.remove("busy");
    $("quality-btn").disabled = false;
    $("cancel-btn").hidden = true;
    showError("查询任务失败：" + err.message);
  }
}

function renderJobStatus(job) {
  const labels = { queued: "排队中", running: "生成中…", done: "完成", error: "失败", canceled: "已取消" };
  $("job-status").textContent = labels[job.status] || job.status;
  $("job-status").style.color = job.status === "error" || job.status === "canceled" ? "var(--err)" : "var(--muted)";
  const wrap = $("progress-wrap");
  if (job.status === "queued" || job.status === "running") {
    wrap.hidden = false;
    $("cancel-btn").hidden = false;
    const pct = Math.max(0, Math.min(100, Number(job.progress) || 0));
    $("progress-bar").style.width = pct + "%";
    if (job.status === "queued" && job.queue_pos) {
      $("progress-text").textContent = `排队中（第 ${job.queue_pos} 位）…`;
    } else {
      const stage = job.stage || labels[job.status];
      $("progress-text").textContent = pct > 0 ? `${stage} ${pct}%` : stage;
    }
  } else {
    wrap.hidden = true;
    $("cancel-btn").hidden = true;
  }
  pollQueueStatus();
}

/* ---------------- 结果区多图查看 ---------------- */
function imageUrl(jobId, index) {
  return `/mpwe/jobs/${jobId}/images/${index}`;
}

function setViewer(jobId, images, index) {
  state.currentJobId = jobId;
  state.currentJobImages = images || [];
  state.currentImageIndex = Math.max(0, Math.min((images || []).length - 1, index || 0));
  const imgs = state.currentJobImages;
  $("result-placeholder").hidden = true;
  const img = $("result-image");
  img.src = imageUrl(jobId, state.currentImageIndex);
  img.hidden = false;

  const multi = imgs.length > 1;
  $("result-nav").hidden = !multi;
  $("result-thumbs").hidden = !multi;
  if (multi) {
    $("img-counter").textContent = `${state.currentImageIndex + 1} / ${imgs.length}`;
    renderThumbs();
  }
}

function renderThumbs() {
  const box = $("result-thumbs");
  box.innerHTML = "";
  state.currentJobImages.forEach((imgMeta, i) => {
    const thumb = document.createElement("img");
    thumb.src = imageUrl(state.currentJobId, i);
    thumb.loading = "lazy";
    thumb.className = "thumb" + (i === state.currentImageIndex ? " active" : "");
    thumb.title = `第 ${i + 1} 张`;
    thumb.addEventListener("click", () => setViewer(state.currentJobId, state.currentJobImages, i));
    box.appendChild(thumb);
  });
}

function stepImage(delta) {
  if (!state.currentJobImages.length) return;
  const n = state.currentJobImages.length;
  const next = (state.currentImageIndex + delta + n) % n;
  setViewer(state.currentJobId, state.currentJobImages, next);
}

/* ---------------- 图片放大查看（灯箱） ---------------- */
function openLightbox() {
  const imgs = state.currentJobImages;
  if (!imgs.length) return;
  setLightboxZoom(1);
  const idx = state.currentImageIndex;
  $("lightbox-img").src = imageUrl(state.currentJobId, idx);
  $("lightbox-counter").textContent = `${idx + 1} / ${imgs.length}`;
  const dl = $("lightbox-download");
  dl.href = imageUrl(state.currentJobId, idx);
  dl.setAttribute("download", `MPWE_${state.currentJobId}_${idx + 1}.png`);
  $("lightbox-prev").hidden = imgs.length <= 1;
  $("lightbox-next").hidden = imgs.length <= 1;
  $("lightbox").hidden = false;
}

function closeLightbox() {
  $("lightbox").hidden = true;
}

function setLightboxZoom(scale) {
  state.lightboxZoom = Math.max(1, Math.min(8, scale));
  clampLightboxPan();
  applyLightboxTransform();
  $("lightbox-zoom").textContent = `${Math.round(state.lightboxZoom * 100)}%`;
  $("lightbox-img").classList.toggle("zoomed", state.lightboxZoom > 1);
}

function applyLightboxTransform() {
  const img = $("lightbox-img");
  if (state.lightboxZoom <= 1) {
    img.style.transform = "";
    return;
  }
  img.style.transform =
    `translate(${state.lightboxPanX}px, ${state.lightboxPanY}px) scale(${state.lightboxZoom})`;
}

function clampLightboxPan() {
  const img = $("lightbox-img");
  const z = state.lightboxZoom;
  if (z <= 1) {
    state.lightboxPanX = 0;
    state.lightboxPanY = 0;
    return;
  }
  // offsetWidth/Height 不包含 transform，是缩放前的实际显示尺寸
  const scaledW = img.offsetWidth * z;
  const scaledH = img.offsetHeight * z;
  const pad = 24;
  const maxX = Math.max(0, (scaledW - window.innerWidth) / 2 + pad);
  const maxY = Math.max(0, (scaledH - window.innerHeight) / 2 + pad);
  state.lightboxPanX = Math.max(-maxX, Math.min(maxX, state.lightboxPanX));
  state.lightboxPanY = Math.max(-maxY, Math.min(maxY, state.lightboxPanY));
}

function stepLightbox(delta) {
  if (!state.currentJobImages.length) return;
  const n = state.currentJobImages.length;
  state.currentImageIndex = (state.currentImageIndex + delta + n) % n;
  setViewer(state.currentJobId, state.currentJobImages, state.currentImageIndex);
  openLightbox();
}

/* ---------------- 任务取消 ---------------- */
async function cancelCurrentJob() {
  const jobId = state.pollingJobId;
  if (!jobId) return;
  const btn = $("cancel-btn");
  btn.disabled = true;
  $("progress-text").textContent = "正在取消…";
  try {
    await fetchJSON(`/mpwe/jobs/${jobId}/cancel`, { method: "POST" });
    $("job-status").textContent = "已取消";
    $("progress-wrap").hidden = true;
    btn.hidden = true;
    $("generate-btn").disabled = !canGenerate();
    $("generate-btn").classList.remove("busy");
    $("quality-btn").disabled = false;
  } catch (err) {
    btn.disabled = false;
    $("progress-text").textContent = "取消失败：" + err.message;
  }
}

/* ---------------- AI 提示词 Agent ---------------- */
function currentModelFile() {
  const type = $("model_type").value;
  return type === "checkpoint" ? $("checkpoint").value : $("unet").value;
}

async function loadAgentAgents() {
  try {
    const data = await fetchJSON("/mpwe/prompt/agents");
    state.agentModels = data.agents || {};
  } catch (_) {
    state.agentModels = {};
  }
  updateAgentAvailability();
}

function updateAgentAvailability() {
  const btn = $("agent-btn");
  const hint = $("agent-hint");
  const model = currentModelFile();
  const agentName = state.agentModels[model];
  if (agentName && state.currentUser) {
    btn.disabled = false;
    hint.textContent = `当前模型已匹配专属 Agent：「${agentName}」，用大白话描述即可生成提示词`;
  } else if (!state.currentUser) {
    btn.disabled = true;
    hint.textContent = "请先登录 / 注册后再使用";
  } else if (model) {
    btn.disabled = true;
    hint.textContent = "当前模型暂未配置专属 Agent，可在管理后台「AI 提示词 Agent」页查看与配置（一个模型对应一个 Agent）";
  } else {
    btn.disabled = true;
    hint.textContent = "用大白话描述你想画的画面，Agent 会自动生成所选模型特调的完整提示词";
  }
}

async function translatePrompt() {
  hideError();
  const model = currentModelFile();
  if (!state.agentModels[model]) {
    showError("当前模型暂未配置专属 Agent，可在管理后台「AI 提示词 Agent」页查看与配置");
    return;
  }
  const text = $("agent_input").value.trim();
  if (!text) {
    showError("请先输入你想画的画面描述");
    return;
  }
  const btn = $("agent-btn");
  btn.disabled = true;
  btn.classList.add("busy");
  $("agent-status").textContent = "";
  $("agent-brief").hidden = true;
  $("agent-progress-wrap").hidden = false;
  $("agent-progress-bar").style.width = "0%";
  $("agent-progress-text").textContent = "提交中…";
  try {
    const job = await fetchJSON("/mpwe/prompt/translate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, model }),
    });
    pollPromptJob(job.job_id);
  } catch (err) {
    btn.disabled = false;
    btn.classList.remove("busy");
    $("agent-status").textContent = "";
    $("agent-progress-wrap").hidden = true;
    showError("提交翻译任务失败：" + err.message);
  }
}

async function pollPromptJob(jobId) {
  try {
    const job = await fetchJSON(`/mpwe/prompt/jobs/${jobId}`);
    const pct = Math.max(0, Math.min(100, Number(job.progress) || 0));
    $("agent-progress-bar").style.width = pct + "%";
    $("agent-progress-text").textContent = (job.stage || "") + (pct > 0 ? ` ${pct}%` : "");
    if (job.status === "queued" || job.status === "running") {
      setTimeout(() => pollPromptJob(jobId), 1200);
      return;
    }
    const btn = $("agent-btn");
    btn.disabled = false;
    btn.classList.remove("busy");
    if (job.status === "done" && job.result) {
      $("agent-progress-bar").style.width = "100%";
      $("agent-progress-text").textContent = "提示词已生成 100%";
      $("prompt").value = job.result.positive || "";
      $("negative_prompt").value = job.result.negative || "";
      $("agent-status").textContent =
        `已由「${job.result.agent_name || "Agent"}」生成（模型特调），可手改后生成`;
      if (job.result.brief) {
        $("agent-brief-text").textContent = job.result.brief;
        $("agent-brief").hidden = false;
      }
      setTimeout(() => { $("agent-progress-wrap").hidden = true; }, 1500);
    } else if (job.status === "error") {
      $("agent-status").textContent = "";
      $("agent-progress-wrap").hidden = true;
      showError("提示词生成失败：" + (job.error || "未知错误"));
    }
  } catch (err) {
    $("agent-btn").disabled = false;
    $("agent-btn").classList.remove("busy");
    $("agent-status").textContent = "";
    $("agent-progress-wrap").hidden = true;
    showError("查询翻译任务失败：" + err.message);
  }
}

/* ---------------- 历史记录 ---------------- */
async function loadHistory() {
  try {
    const data = await fetchJSON("/mpwe/jobs?limit=30");
    const list = $("history");
    list.innerHTML = "";
    for (const job of data.jobs) {
      if (job.status !== "done" || job.images.length === 0) continue;
      state.historyImages[job.id] = job.images;
      const li = document.createElement("li");
      li.className = "history-item";
      const params = job.params || {};
      const model = params.checkpoint || params.unet_name || job.workflow || "";
      li.title = `${job.workflow} · ${job.images.length} 张 · ${new Date(job.created_at * 1000).toLocaleString()}`;
      const title = document.createElement("div");
      title.className = "history-title";
      title.textContent = `#${job.id.slice(0, 8)} · ${job.images.length} 张 · ${model.split(".")[0]}`;
      const meta = document.createElement("div");
      meta.className = "history-meta muted";
      meta.textContent = new Date(job.created_at * 1000).toLocaleString() + "（点击加载图片）";
      li.appendChild(title);
      li.appendChild(meta);
      li.addEventListener("click", () => {
        state.lastImage = job.images[0];
        $("quality-panel").hidden = false;
        setViewer(job.id, job.images, 0);
        $("job-status").textContent = `历史 · ${job.id}`;
      });
      list.appendChild(li);
    }
  } catch (_) { /* 历史加载失败不阻塞页面 */ }
}

/* ---------------- 登录 / 注册 ---------------- */
function showAuthModal() {
  $("auth-modal").hidden = false;
  switchAuthTab("login");
}

function hideAuthModal() {
  $("auth-modal").hidden = true;
}

function switchAuthTab(tab) {
  document.querySelectorAll(".auth-tab").forEach((b) =>
    b.classList.toggle("active", b.dataset.tab === tab)
  );
  $("login-form").hidden = tab !== "login";
  $("register-form").hidden = tab !== "register";
}

/* ---------------- 免费充值额度（Turnstile 人机验证） ---------------- */
function renderFreeTurnstile() {
  const box = $("free-turnstile-box");
  box.innerHTML = "";
  state.turnstileToken = "";
  $("free-claim-submit").disabled = true;
  $("free-turnstile-status").hidden = true;
  $("free-turnstile-retry").hidden = true;
  if (!state.turnstileSiteKey) {
    showFreeTurnstileError("人机验证未配置，请联系管理员。");
    return;
  }
  let retries = 0;
  const tryRender = () => {
    if (!window.turnstile) {
      if (retries++ < 40) {
        setTimeout(tryRender, 300);
      } else {
        showFreeTurnstileError("人机验证服务加载失败（可能被网络屏蔽）。点「重新验证」重试，或联系管理员。");
      }
      return;
    }
    try {
      state.turnstileWidgetId = window.turnstile.render(box, {
        sitekey: state.turnstileSiteKey,
        callback: (token) => {
          state.turnstileToken = token;
          $("free-claim-submit").disabled = !token;
          $("free-turnstile-status").hidden = true;
          $("free-turnstile-retry").hidden = true;
        },
        "expired-callback": () => {
          state.turnstileToken = "";
          $("free-claim-submit").disabled = true;
          showFreeTurnstileError("验证已过期，请重新验证。");
        },
        "error-callback": (code) => {
          state.turnstileToken = "";
          $("free-claim-submit").disabled = true;
          showFreeTurnstileError(`人机验证服务出错（${code}），点「重新验证」重试。`);
        },
      });
    } catch (err) {
      showFreeTurnstileError("人机验证组件初始化失败：" + err.message);
    }
  };
  tryRender();
}

function showFreeTurnstileError(message) {
  const st = $("free-turnstile-status");
  st.textContent = message;
  st.hidden = false;
  $("free-turnstile-retry").hidden = false;
}

function retryFreeTurnstile() {
  if (window.turnstile && state.turnstileWidgetId != null) {
    try {
      window.turnstile.remove(state.turnstileWidgetId);
    } catch (_) { /* ignore */ }
  }
  if (!window.turnstile) {
    // api.js 没加载成功时重新注入
    const s = document.createElement("script");
    s.src = "https://challenges.cloudflare.com/turnstile/v0/api.js";
    s.async = true;
    s.onload = () => renderFreeTurnstile();
    document.head.appendChild(s);
    return;
  }
  renderFreeTurnstile();
}

function openFreeModal() {
  $("free-modal").hidden = false;
  $("free-claim-msg").textContent = "";
  const fr = state.billing.free_recharge || {};
  const api = fr.api != null ? Number(fr.api).toFixed(2) : "—";
  const img = fr.image != null ? Number(fr.image).toFixed(2) : "—";
  $("free-desc").innerHTML =
    `通过人机验证后，一次性到账：<b>API 🥈${api} 银币</b> + <b>图片 🪙${img} 金币</b>（每账号限一次）。`;
  renderFreeTurnstile();
}

function closeFreeModal() {
  $("free-modal").hidden = true;
}

async function submitFreeClaim() {
  const btn = $("free-claim-submit");
  const msg = $("free-claim-msg");
  msg.textContent = "";
  btn.disabled = true;
  try {
    const data = await authPost("/mpwe/auth/free-claim", {
      turnstile_token: state.turnstileToken,
    });
    state.currentUser = data.user;
    updateUserUI();
    const fr = state.billing.free_recharge || {};
    msg.textContent =
      `到账成功！API +${fr.api ?? 0.5} 银币，图片 +${fr.image ?? 3} 金币。`;
    setTimeout(closeFreeModal, 1200);
  } catch (err) {
    msg.textContent = "领取失败：" + err.message;
    btn.disabled = !state.turnstileToken;
    if (state.turnstileWidgetId != null && window.turnstile) {
      window.turnstile.reset(state.turnstileWidgetId);
    }
    renderFreeTurnstile();
  }
}

async function authPost(url, payload) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 45000);
  let resp;
  try {
    resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: ctrl.signal,
    });
  } catch (err) {
    clearTimeout(timer);
    if (err.name === "AbortError") throw new Error("请求超时，请重试");
    throw err;
  }
  clearTimeout(timer);
  let data = {};
  try {
    data = await resp.json();
  } catch (_) { /* ignore */ }
  if (!resp.ok) throw new Error(data.detail || resp.statusText);
  return data;
}

async function submitLogin(e) {
  e.preventDefault();
  const msg = $("login-msg");
  msg.textContent = "";
  try {
    const data = await authPost("/mpwe/auth/login", {
      username: $("login-username").value.trim(),
      password: $("login-password").value,
    });
    state.currentUser = data.user;
    afterAuthSuccess();
  } catch (err) {
    msg.textContent = "登录失败：" + err.message;
  }
}

async function submitRegister(e) {
  e.preventDefault();
  const msg = $("reg-msg");
  msg.textContent = "";
  try {
    const data = await authPost("/mpwe/auth/register", {
      username: $("reg-username").value.trim(),
      password: $("reg-password").value,
      invite_code: $("reg-invite").value.trim(),
    });
    state.currentUser = data.user;
    afterAuthSuccess();
  } catch (err) {
    msg.textContent = "注册失败：" + err.message;
  }
}

function afterAuthSuccess() {
  hideAuthModal();
  updateUserUI();
  $("login-username").value = "";
  $("login-password").value = "";
  $("reg-username").value = "";
  $("reg-password").value = "";
  $("reg-invite").value = "";
  loadHistory();
  refreshMe();
}

function updateUserUI() {
  const area = $("user-area");
  if (!state.currentUser) {
    area.hidden = true;
    $("generate-btn").disabled = true;
    updateAgentAvailability();
    return;
  }
  area.hidden = false;
  $("user-chip").textContent = `#${state.currentUser.uid} ${state.currentUser.username}`;
  const w = state.currentUser.wallets || {};
  const fmt = (mli) => (mli / 1000).toFixed(2);
  $("wallet-chip").textContent = `API 🥈${fmt(w.api_balance_mli || 0)} · 图片 🪙${fmt(w.image_balance_mli || 0)}`;
  const claimBtn = $("free-claim-btn");
  claimBtn.hidden = false;
  claimBtn.disabled = !!state.currentUser.free_claimed;
  claimBtn.textContent = state.currentUser.free_claimed ? "🪙 已领取" : "🪙 免费充值额度";
  $("generate-btn").disabled = !canGenerate();
  updateAgentAvailability();
}

async function refreshMe() {
  try {
    const data = await fetchJSON("/mpwe/auth/me");
    state.currentUser = data.user;
    updateUserUI();
    return data.user;
  } catch (_) {
    state.currentUser = null;
    updateUserUI();
    return null;
  }
}

async function logout() {
  try {
    await authPost("/mpwe/auth/logout", {});
  } catch (_) { /* ignore */ }
  state.currentUser = null;
  location.reload();
}

/* ---------------- 提示与工具 ---------------- */
function showError(message) {
  const box = $("error-box");
  box.textContent = message;
  box.hidden = false;
}

function hideError() {
  $("error-box").hidden = true;
}

$("generate-btn").addEventListener("click", generate);
$("agent-btn").addEventListener("click", translatePrompt);
$("cancel-btn").addEventListener("click", cancelCurrentJob);
$("result-image").addEventListener("click", openLightbox);
$("prev-img").addEventListener("click", () => stepImage(-1));
$("next-img").addEventListener("click", () => stepImage(1));
$("lightbox-close").addEventListener("click", (e) => { e.stopPropagation(); closeLightbox(); });
$("lightbox-prev").addEventListener("click", (e) => { e.stopPropagation(); stepLightbox(-1); });
$("lightbox-next").addEventListener("click", (e) => { e.stopPropagation(); stepLightbox(1); });
$("lightbox-download").addEventListener("click", (e) => e.stopPropagation());
document.querySelector("#lightbox .lightbox-stage").addEventListener("click", (e) => e.stopPropagation());
$("lightbox").addEventListener("wheel", (e) => {
  e.preventDefault();
  const factor = e.deltaY > 0 ? 1 / 1.12 : 1.12;
  setLightboxZoom(state.lightboxZoom * factor);
}, { passive: false });
$("lightbox-img").addEventListener("dblclick", (e) => {
  e.stopPropagation();
  setLightboxZoom(1);
});
$("lightbox-zoom").addEventListener("click", (e) => {
  e.stopPropagation();
  setLightboxZoom(1);
});
$("lightbox-img").addEventListener("pointerdown", (e) => {
  state.suppressCloseUntil = 0;
  if (state.lightboxZoom <= 1) return;
  e.preventDefault();
  state.lightboxDrag = {
    id: e.pointerId,
    startX: e.clientX,
    startY: e.clientY,
    panX: state.lightboxPanX,
    panY: state.lightboxPanY,
    moved: false,
  };
  e.currentTarget.setPointerCapture(e.pointerId);
  e.currentTarget.classList.add("dragging");
});
$("lightbox-img").addEventListener("pointermove", (e) => {
  const drag = state.lightboxDrag;
  if (!drag || drag.id !== e.pointerId) return;
  const dx = e.clientX - drag.startX;
  const dy = e.clientY - drag.startY;
  if (!drag.moved && Math.hypot(dx, dy) > 3) drag.moved = true;
  state.lightboxPanX = drag.panX + dx;
  state.lightboxPanY = drag.panY + dy;
  clampLightboxPan();
  applyLightboxTransform();
});
function endLightboxDrag(e) {
  const drag = state.lightboxDrag;
  if (!drag || drag.id !== e.pointerId) return;
  state.lightboxDrag = null;
  $("lightbox-img").classList.remove("dragging");
  if (drag.moved) state.suppressCloseUntil = Date.now() + 300;
}
$("lightbox-img").addEventListener("pointerup", endLightboxDrag);
$("lightbox-img").addEventListener("pointercancel", endLightboxDrag);
document.addEventListener("keydown", (e) => {
  if (!$("lightbox").hidden) {
    if (e.key === "Escape") closeLightbox();
    if (e.key === "ArrowLeft") stepLightbox(-1);
    if (e.key === "ArrowRight") stepLightbox(1);
  }
});
$("quality-btn").addEventListener("click", () => {
  if (!state.lastImage) {
    showError("请先生成一张图片，再进行画质增强");
    return;
  }
  hideError();
  submitJob(collectParams(true));
});
$("random-seed").addEventListener("click", () => {
  $("seed").value = Math.floor(Math.random() * 2 ** 32);
});
$("model_type").addEventListener("change", applyModelPreset);
$("unet").addEventListener("change", applyDiffusionPreset);
$("checkpoint").addEventListener("change", applyCheckpointPreset);
$("width").addEventListener("input", syncResolutionPresetActive);
$("height").addEventListener("input", syncResolutionPresetActive);
$("lightbox").addEventListener("click", (e) => {
  if (Date.now() < state.suppressCloseUntil) return;
  closeLightbox();
});
document.querySelectorAll(".auth-tab").forEach((b) =>
  b.addEventListener("click", () => switchAuthTab(b.dataset.tab))
);
$("login-form").addEventListener("submit", submitLogin);
$("register-form").addEventListener("submit", submitRegister);
$("logout-btn").addEventListener("click", logout);
$("free-claim-btn").addEventListener("click", openFreeModal);
$("free-claim-submit").addEventListener("click", submitFreeClaim);
$("free-turnstile-retry").addEventListener("click", retryFreeTurnstile);
$("free-modal-close").addEventListener("click", closeFreeModal);

/* ---------------- 初始化 ---------------- */
(async function init() {
  try {
    const cfg = await fetchJSON("/mpwe/config");
    state.turnstileSiteKey = (cfg.turnstile && cfg.turnstile.site_key) || "";
    state.billing = cfg.billing || { signup_bonus: {}, free_recharge: {} };
    const sb = state.billing.signup_bonus || {};
    if (sb.api != null && sb.image != null) {
      $("reg-hint").textContent =
        `需要管理员发放的邀请码；注册后自动登录。新账号含 API 🥈${Number(sb.api).toFixed(2)} 银币 + 图片 🪙${Number(sb.image).toFixed(2)} 金币，右上角还可领取一次免费充值额度。`;
    }
  } catch (_) { /* ignore */ }
  await loadAgentAgents();
  const user = await refreshMe();
  if (!user) showAuthModal();
  await refreshHealth();
  if (state.comfyuiConnected) {
    state.optionsLoaded = true;
    await loadOptions();
  }
  if (user) await loadHistory();
  setInterval(refreshHealth, 10000);
})();
