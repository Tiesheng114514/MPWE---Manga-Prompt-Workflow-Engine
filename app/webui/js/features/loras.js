/* LoRA 叠加面板逻辑（勾选 + 权重）。依赖 app.js 中的 $ 与 state。 */
"use strict";

function applyLoraPreset(loras) {
  state.loraPresets = {};
  for (const item of loras || []) {
    if (item.file) state.loraPresets[item.file] = item;
  }
  renderLoraList();
}

function renderLoraList() {
  const list = $("lora-list");
  list.innerHTML = "";
  if (!state.loraModels.length) {
    list.innerHTML = '<span class="hint">（未连接绘画GPU服务器或无 LoRA 文件）</span>';
    return;
  }
  for (const file of state.loraModels) {
    const preset = state.loraPresets[file] || {};
    const row = document.createElement("label");
    row.className = "lora-row";
    row.dataset.file = file;
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = !!preset.default;
    const name = document.createElement("span");
    name.className = "lora-name";
    name.textContent = preset.name ? preset.name : file;
    name.title = file + (preset.notes ? "\n" + preset.notes : "");
    const weight = document.createElement("input");
    weight.type = "number";
    weight.className = "lora-weight";
    weight.step = "0.05";
    weight.min = "-2";
    weight.max = "2";
    weight.value = preset.weight != null ? preset.weight : 0.6;
    weight.disabled = !cb.checked;
    cb.addEventListener("change", () => {
      weight.disabled = !cb.checked;
    });
    row.appendChild(cb);
    row.appendChild(name);
    row.appendChild(weight);
    list.appendChild(row);
  }
}

function collectLoraParams() {
  return Array.from(document.querySelectorAll("#lora-list .lora-row")).map((row) => {
    const cb = row.querySelector('input[type="checkbox"]');
    const weight = row.querySelector(".lora-weight");
    if (!cb.checked) return null;
    return { file: row.dataset.file, weight: parseFloat(weight.value) || 0 };
  }).filter(Boolean);
}
