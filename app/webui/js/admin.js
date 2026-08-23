/* MPWE 管理员后台前端逻辑（独立服务 8643 版）。
   注意：管理后台是独立 FastAPI 服务（app/admin_server.py），
   页面在 / 与 /login，所有接口在 /api/*；与用户 WebUI（8642）完全分离。 */
"use strict";

const $ = (id) => document.getElementById(id);
const API = "/api";

async function fetchJSON(url, options) {
  const opts = options || {};
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), opts.timeout || 30000);
  let resp;
  try {
    resp = await fetch(url, { ...opts, signal: ctrl.signal });
  } catch (err) {
    clearTimeout(timer);
    if (err.name === "AbortError") throw new Error("请求超时");
    throw err;
  }
  clearTimeout(timer);
  let data = {};
  try {
    data = await resp.json();
  } catch (_) { /* ignore */ }
  if (!resp.ok) {
    const err = new Error(data.detail || data.error || resp.statusText);
    err.status = resp.status;
    throw err;
  }
  return data;
}

/* ---------------- 登录页 ---------------- */
function showLoginError(msg) {
  $("login-error").textContent = msg;
  $("login-error").hidden = false;
}

function hideLoginError() {
  $("login-error").hidden = true;
}

async function login() {
  hideLoginError();
  const password = $("password").value;
  if (!password) {
    showLoginError("请输入管理密码");
    return;
  }
  const btn = $("login-btn");
  btn.disabled = true;
  btn.classList.add("busy");
  try {
    await fetchJSON(`${API}/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    location.href = "/";
  } catch (err) {
    showLoginError(err.message);
    btn.disabled = false;
    btn.classList.remove("busy");
  }
}

/* ---------------- 管理后台 ---------------- */
const state = { agents: [] };

async function logout() {
  try {
    await fetchJSON(`${API}/logout`, { method: "POST" });
  } catch (_) { /* ignore */ }
  location.href = "/login";
}

async function loadOverview() {
  try {
    const data = await fetchJSON(`${API}/overview`);
    const cards = [
      ["后端版本", data.version],
      ["绘画GPU服务器", data.comfyui_connected ? "在线" : "离线"],
      ["LLM API Key", data.llm_configured ? "已配置" : "未配置"],
      ["LLM 模型", data.llm_model || "—"],
      ["管理密码", data.password_set ? "已设置" : "未设置"],
      ["AI Agent 适配模型", Object.keys(data.agent_models || {}).join("、") || "无"],
      ["用户数", data.users_count || 0],
      ["邀请码", `${data.invite_codes_count || 0}（已用 ${data.invite_codes_used || 0} 名额）`],
      ["API 总消耗", `🥈${fmtYuan(data.api_total_mli)}（${data.api_calls || 0} 次 / ${data.api_tokens || 0} token）`],
      ["图片总计费", `🪙${fmtYuan(data.image_total_mli)}（${data.image_count || 0} 张 × 🪙${data.image_price_yuan || 0}）`],
      ["GPU 总算力", fmtGpu(data.gpu_total_tflops_hour)],
      ["GPU 总耗时", `${data.gpu_total_seconds || 0} 秒`],
    ];
    $("overview-cards").innerHTML = cards
      .map(([k, v]) => `<div class="overview-card"><h3>${k}</h3><p>${v}</p></div>`)
      .join("");
  } catch (err) {
    if (err.status === 401) {
      location.href = "/login";
      return;
    }
    $("overview-cards").textContent = "加载概览失败：" + err.message;
  }
}

async function loadAgents() {
  try {
    const data = await fetchJSON(`${API}/prompts`);
    state.agents = data.agents || [];
    const select = $("agent-select");
    select.innerHTML = "";
    for (const a of state.agents) {
      const label = a.model_file
        ? `${a.name}（${a.model_file}）`
        : `${a.name}（共用·所有模型）`;
      const opt = document.createElement("option");
      opt.value = a.id;
      opt.textContent = label;
      select.appendChild(opt);
    }
    if (state.agents.length > 0) applyAgentSelection();
    else $("agent-save-status").textContent = "未找到可编辑的 Agent。";
  } catch (err) {
    if (err.status === 401) {
      location.href = "/login";
      return;
    }
    $("agent-save-status").textContent = "加载 Agent 列表失败：" + err.message;
  }
}

function applyAgentSelection() {
  const a = state.agents.find((x) => x.id === $("agent-select").value);
  if (!a) return;
  $("agent-name").value = a.name;
  $("agent-desc").value = a.description;
  $("agent-prompt").value = a.prompt;
  $("agent-save-status").textContent = "";
}

async function saveAgent() {
  const btn = $("agent-save-btn");
  const status = $("agent-save-status");
  btn.disabled = true;
  btn.classList.add("busy");
  status.textContent = "保存中…";
  try {
    await fetchJSON(`${API}/prompts/${encodeURIComponent($("agent-select").value)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: $("agent-name").value,
        description: $("agent-desc").value,
        prompt: $("agent-prompt").value,
      }),
    });
    status.textContent = "已保存，立即生效。";
    await loadAgents();
  } catch (err) {
    status.textContent = "保存失败：" + err.message;
  } finally {
    btn.disabled = false;
    btn.classList.remove("busy");
  }
}

async function changePassword() {
  const old = $("pwd-old").value;
  const p1 = $("pwd-new").value;
  const p2 = $("pwd-confirm").value;
  const status = $("pwd-status");
  if (!old || !p1 || !p2) {
    status.textContent = "请填写完整。";
    return;
  }
  if (p1 !== p2) {
    status.textContent = "两次新密码不一致。";
    return;
  }
  const btn = $("pwd-btn");
  btn.disabled = true;
  btn.classList.add("busy");
  status.textContent = "修改中…";
  try {
    await fetchJSON(`${API}/password`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ old, new: p1 }),
    });
    status.textContent = "密码已更新。";
    $("pwd-old").value = "";
    $("pwd-new").value = "";
    $("pwd-confirm").value = "";
  } catch (err) {
    status.textContent = "修改失败：" + err.message;
  } finally {
    btn.disabled = false;
    btn.classList.remove("busy");
  }
}

/* ---------------- 工具 ---------------- */
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

const fmtYuan = (mli) => (Number(mli || 0) / 1000).toFixed(2);
const fmtTime = (ts) => (ts ? new Date(ts * 1000).toLocaleString() : "—");
const fmtGpu = (tf) => {
  const v = Number(tf || 0);
  if (v >= 1) return v.toFixed(3) + " TFLOPS·时";
  if (v >= 1e-3) return (v * 1e3).toFixed(3) + " GFLOPS·时";
  return (v * 1e6).toFixed(1) + " MFLOPS·时";
};

/* ---------------- 邀请码 ---------------- */
async function loadInviteCodes() {
  try {
    const data = await fetchJSON(`${API}/invite-codes`);
    const body = $("invite-codes-body");
    body.innerHTML = "";
    for (const c of data.invite_codes || []) {
      const tr = document.createElement("tr");
      const used = Number(c.used_count || 0);
      const usedUp = used >= Number(c.max_invites);
      tr.innerHTML = `
        <td><code>${esc(c.code)}</code></td>
        <td>${used} / ${c.max_invites}${usedUp ? "（已满）" : ""}</td>
        <td>${fmtTime(c.created_at)}</td>
        <td>
          <button class="btn-ghost" data-code="${esc(c.code)}" ${used > 0 ? "disabled title='已有用户注册，不能删除'" : ""}>删除</button>
        </td>`;
      tr.querySelector("button").addEventListener("click", async () => {
        if (!confirm(`确定删除邀请码 ${c.code}？`)) return;
        try {
          await fetchJSON(`${API}/invite-codes/${encodeURIComponent(c.code)}`, { method: "DELETE" });
          await loadInviteCodes();
        } catch (err) {
          alert("删除失败：" + err.message);
        }
      });
      body.appendChild(tr);
    }
  } catch (err) {
    $("invite-codes-body").innerHTML = `<tr><td colspan="4">加载失败：${esc(err.message)}</td></tr>`;
  }
}

async function createInviteCodes() {
  const btn = $("invite-create-btn");
  const status = $("invite-create-status");
  const codes = $("invite-codes-input").value.split("\n").map((s) => s.trim()).filter(Boolean);
  if (!codes.length) {
    status.textContent = "请先填写邀请码（每行一个）。";
    return;
  }
  btn.disabled = true;
  status.textContent = "创建中…";
  try {
    const data = await fetchJSON(`${API}/invite-codes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ codes, max_invites: parseInt($("invite-max-input").value, 10) }),
    });
    status.textContent = `已创建 ${(data.created || []).length} 个邀请码。`;
    $("invite-codes-input").value = "";
    await loadInviteCodes();
  } catch (err) {
    status.textContent = "创建失败：" + err.message;
  } finally {
    btn.disabled = false;
  }
}

/* ---------------- 用户管理 ---------------- */
async function loadUsers() {
  try {
    const data = await fetchJSON(`${API}/users`);
    const body = $("users-body");
    body.innerHTML = "";
    for (const u of data.users || []) {
      const tr = document.createElement("tr");
      const w = u.wallets || {};
      tr.innerHTML = `
        <td>${esc(u.uid)}</td>
        <td>${esc(u.username)}</td>
        <td><code>${esc(u.invite_code || "—")}</code></td>
        <td>${u.status === "active" ? "启用" : "停用"}</td>
        <td>🥈${fmtYuan(w.api_balance_mli)}</td>
        <td>🪙${fmtYuan(w.image_balance_mli)}</td>
        <td>🥈${fmtYuan((u.api || {}).amount_mli)}</td>
        <td>🪙${fmtYuan((u.image || {}).amount_mli)}</td>
        <td>${fmtGpu((u.gpu || {}).tflops_hour)}</td>
        <td><button class="btn-ghost" data-uid="${esc(u.uid)}">详情</button></td>`;
      tr.querySelector("button").addEventListener("click", () => showUserDetail(u.uid));
      body.appendChild(tr);
    }
  } catch (err) {
    $("users-body").innerHTML = `<tr><td colspan="10">加载失败：${esc(err.message)}</td></tr>`;
  }
}

async function showUserDetail(uid) {
  try {
    const data = await fetchJSON(`${API}/users/${uid}`);
    const u = data.user;
    const w = u.wallets || {};
    const panel = $("user-detail");
    panel.hidden = false;
    panel.innerHTML = `
      <h3>用户 #${esc(u.uid)} ${esc(u.username)}（${u.status === "active" ? "启用" : "停用"}）</h3>
      <p class="desc">邀请码：<code>${esc(u.invite_code || "—")}</code> · 注册：${fmtTime(u.created_at)} · 最近登录：${fmtTime(u.last_login_at)}</p>
      <div class="overview-cards">
        <div class="overview-card"><h3>API 钱包（银币）</h3><p>🥈${fmtYuan(w.api_balance_mli)}</p></div>
        <div class="overview-card"><h3>图片钱包</h3><p>🪙${fmtYuan(w.image_balance_mli)}</p></div>
        <div class="overview-card"><h3>API 已消耗（银币）</h3><p>🥈${fmtYuan((u.api || {}).amount_mli)}</p></div>
        <div class="overview-card"><h3>图片已消耗</h3><p>🪙${fmtYuan((u.image || {}).amount_mli)}</p></div>
        <div class="overview-card"><h3>GPU 算力</h3><p>${fmtGpu((u.gpu || {}).tflops_hour)}</p></div>
      </div>
      <div class="form-block">
        <h3>充值 / 调整余额</h3>
        <div class="form-row">
          <select id="recharge-wallet">
            <option value="api">API 钱包（银币）</option>
            <option value="image">图片钱包（金币）</option>
          </select>
          <input id="recharge-amount" type="number" step="0.01" placeholder="金额（金币，负数为扣回）">
          <input id="recharge-note" type="text" placeholder="备注（可选）">
          <button id="recharge-btn" class="btn-primary" type="button">确认调整</button>
        </div>
        <div class="form-row">
          <button id="toggle-user-btn" class="btn-ghost" type="button">${u.status === "active" ? "停用账号" : "启用账号"}</button>
          <button id="reset-pwd-btn" class="btn-ghost" type="button">重置密码</button>
          <span id="user-op-status" class="status-note"></span>
        </div>
      </div>
      <h3>账单流水</h3>
      <table class="admin-table">
        <thead><tr><th>时间</th><th>类型</th><th>金额</th><th>余额</th><th>明细</th></tr></thead>
        <tbody id="user-entries-body"></tbody>
      </table>`;
    const entriesBody = panel.querySelector("#user-entries-body");
    entriesBody.innerHTML = "";
    for (const e of data.entries || []) {
      const tr = document.createElement("tr");
      let detail = "";
      try {
        const d = JSON.parse(e.detail || "{}");
        if (e.kind === "api") {
          detail = `${d.model || ""} 输入${d.input_cache_miss_tokens || 0}+缓存${d.input_cache_hit_tokens || 0} / 输出${d.output_tokens || 0} token${d.peak ? "（高峰）" : "（闲时）"}`;
        } else if (e.kind === "image") {
          detail = `${d.image_count || 0} 张 × 🪙${d.price_per_image_yuan || 0}`;
        } else {
          detail = esc(d.note || "");
        }
      } catch (_) { /* ignore */ }
      tr.innerHTML = `
        <td>${fmtTime(e.created_at)}</td>
        <td>${esc(e.kind)}</td>
        <td>${(e.amount_mli / 1000).toFixed(3)}</td>
        <td>${(e.balance_after_mli / 1000).toFixed(3)}</td>
        <td>${detail}</td>`;
      entriesBody.appendChild(tr);
    }
    panel.querySelector("#recharge-btn").addEventListener("click", () => rechargeUser(uid));
    panel.querySelector("#toggle-user-btn").addEventListener("click", async () => {
      try {
        await fetchJSON(`${API}/users/${uid}/toggle-active`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({}),
        });
        await loadUsers();
        await showUserDetail(uid);
      } catch (err) {
        panel.querySelector("#user-op-status").textContent = "操作失败：" + err.message;
      }
    });
    panel.querySelector("#reset-pwd-btn").addEventListener("click", async () => {
      const pwd = prompt("输入新密码（8-128 位）");
      if (!pwd) return;
      try {
        await fetchJSON(`${API}/users/${uid}/reset-password`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ new_password: pwd }),
        });
        panel.querySelector("#user-op-status").textContent = "密码已重置。";
      } catch (err) {
        panel.querySelector("#user-op-status").textContent = "重置失败：" + err.message;
      }
    });
  } catch (err) {
    $("user-detail").hidden = true;
    alert("加载用户详情失败：" + err.message);
  }
}

async function rechargeUser(uid) {
  const status = document.getElementById("user-op-status");
  try {
    const data = await fetchJSON(`${API}/users/${uid}/balance`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        wallet: document.getElementById("recharge-wallet").value,
        amount: parseFloat(document.getElementById("recharge-amount").value),
        note: document.getElementById("recharge-note").value,
      }),
    });
    status.textContent = "已调整，当前余额：" + JSON.stringify(data.wallets);
    await loadUsers();
    await showUserDetail(uid);
  } catch (err) {
    status.textContent = "调整失败：" + err.message;
  }
}

/* ---------------- GPU / API 统计 ---------------- */
function totalCards(el, items) {
  $(el).innerHTML = items
    .map(([k, v]) => `<div class="overview-card"><h3>${esc(k)}</h3><p>${esc(v)}</p></div>`)
    .join("");
}

async function loadGpuStats() {
  try {
    const data = await fetchJSON(`${API}/stats/gpu`);
    totalCards("gpu-total-cards", [
      ["总任务数", data.rows.reduce((s, r) => s + (r.jobs || 0), 0)],
      ["总 GPU 耗时", data.total_seconds + " 秒"],
      ["总算力", fmtGpu(data.total_tflops_hour)],
    ]);
    const body = $("gpu-body");
    body.innerHTML = "";
    for (const r of data.rows || []) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${esc(r.user_id)}</td>
        <td>${r.jobs}</td>
        <td>${Number(r.gpu_seconds || 0).toFixed(1)}</td>
        <td>${fmtGpu(r.tflops_hour)}</td>`;
      body.appendChild(tr);
    }
  } catch (err) {
    $("gpu-body").innerHTML = `<tr><td colspan="4">加载失败：${esc(err.message)}</td></tr>`;
  }
}

async function loadApiStats() {
  try {
    const data = await fetchJSON(`${API}/stats/api`);
    totalCards("api-total-cards", [
      ["总请求数", data.total_calls],
      ["总 token", data.total_tokens],
      ["总金额", "🥈" + fmtYuan(data.total_amount_mli)],
    ]);
    const body = $("api-body");
    body.innerHTML = "";
    for (const r of data.rows || []) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${esc(r.user_id)}</td>
        <td>${r.calls}</td>
        <td>${r.tokens}</td>
        <td>🥈${fmtYuan(r.amount_mli)}</td>`;
      body.appendChild(tr);
    }
  } catch (err) {
    $("api-body").innerHTML = `<tr><td colspan="4">加载失败：${esc(err.message)}</td></tr>`;
  }
}

/* ---------------- 初始化 ---------------- */
if (document.getElementById("login-btn")) {
  $("login-btn").addEventListener("click", login);
  $("password").addEventListener("keydown", (e) => {
    if (e.key === "Enter") login();
  });
} else if (document.getElementById("logout-btn")) {
  $("logout-btn").addEventListener("click", logout);
  $("agent-select").addEventListener("change", applyAgentSelection);
  $("agent-save-btn").addEventListener("click", saveAgent);
  $("pwd-btn").addEventListener("click", changePassword);
  $("invite-create-btn").addEventListener("click", createInviteCodes);

  document.querySelectorAll(".admin-nav-item:not(.disabled)").forEach((item) => {
    item.addEventListener("click", (e) => {
      e.preventDefault();
      document.querySelectorAll(".admin-nav-item").forEach((x) => x.classList.toggle("active", x === item));
      document.querySelectorAll(".admin-tab").forEach((s) => s.classList.toggle("active", s.id === "tab-" + item.dataset.tab));
      if (item.dataset.tab === "users") {
        loadInviteCodes();
        loadUsers();
      } else if (item.dataset.tab === "gpu") {
        loadGpuStats();
      } else if (item.dataset.tab === "api_stats") {
        loadApiStats();
      }
    });
  });

  loadOverview();
  loadAgents();
  loadInviteCodes();
  loadUsers();
  loadGpuStats();
  loadApiStats();
}
