// 鱼缸水生态系统看板 —— 前端逻辑
// 每 1 秒轮询后台 /api/state，渲染指标、种群、健康度、趋势图；
// 控件通过 /api/control 施加外部条件。

const API_STATE = "/api/state";
const API_CONTROL = "/api/control";

let currentState = null;
// 正在被用户拖动的滑块 id 集合：拖动态期间，轮询渲染不覆盖这些滑块的值/label
const draggingSliders = new Set();

// ---------------- 工具 ----------------
async function fetchJSON(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) throw new Error("HTTP " + res.status);
  return res.json();
}

function el(id) {
  return document.getElementById(id);
}

function colorFor(value, ideal) {
  if (value >= ideal[0] && value <= ideal[1]) return "var(--good)";
  // 距离理想越远越危险
  const mid = (ideal[0] + ideal[1]) / 2;
  const dist = Math.abs(value - mid);
  const span = Math.max(ideal[1] - ideal[0], 1);
  const ratio = dist / span;
  if (ratio > 1.6) return "var(--bad)";
  if (ratio > 1.0) return "var(--warn)";
  return "var(--good)";
}

// ---------------- 渲染 ----------------
function renderMetrics(state) {
  const metrics = [
    { key: "oxygen", label: "溶解氧", unit: "mg/L", max: 14 },
    { key: "ammonia", label: "氨氮 NH₃", unit: "mg/L", max: 1.5 },
    { key: "nitrite", label: "亚硝酸盐 NO₂", unit: "mg/L", max: 1.5 },
    { key: "nitrate", label: "硝酸盐 NO₃", unit: "mg/L", max: 80 },
    { key: "ph", label: "酸碱度 pH", unit: "", max: 9 },
    { key: "temp", label: "温度", unit: "°C", max: 35 },
  ];
  const grid = el("metric-grid");
  grid.innerHTML = "";
  for (const m of metrics) {
    const v = state[m.key];
    const ideal = state.ideal[m.key];
    const color = colorFor(v, ideal);
    const pct = Math.min(100, (v / m.max) * 100);
    const idealLeft = (ideal[0] / m.max) * 100;
    const idealWidth = ((ideal[1] - ideal[0]) / m.max) * 100;

    const card = document.createElement("div");
    card.className = "metric";
    card.innerHTML =
      '<div class="metric-top">' +
        '<span class="metric-label">' + m.label + "</span>" +
        '<span class="metric-val" style="color:' + color + '">' + v + " " + m.unit + "</span>" +
      "</div>" +
      '<div class="gauge">' +
        '<div class="gauge-ideal" style="left:' + idealLeft + "%;width:" + idealWidth + '%"></div>' +
        '<div class="gauge-fill" style="width:' + pct + "%;background:" + color + '"></div>' +
      "</div>";
    grid.appendChild(card);
  }
}

function renderPop(state) {
  el("pop-fish").textContent = state.fish;
  const fa = state.fish_age || {};
  el("pop-fish-age").textContent =
    "幼 " + (fa.young || 0) + " · 成 " + (fa.adult || 0) + " · 老 " + (fa.senior || 0) +
    " · 均龄 " + (fa.avg_age || 0) + "h";
  el("pop-plants").textContent = state.plants;
  el("pop-bacteria").textContent = state.bacteria;
  el("pop-food").textContent = state.food;
  el("pop-waste").textContent = state.waste;
}

function renderHealth(state) {
  const fill = el("health-fill");
  fill.style.width = state.health + "%";
  const color =
    state.health >= 75 ? "var(--good)" : state.health >= 45 ? "var(--warn)" : "var(--bad)";
  fill.style.background = color;
  const num = el("health-num");
  num.textContent = state.health + " / 100";
  num.style.color = color;
}

function renderMeta(state) {
  el("meta-time").textContent = "时间 " + state.time + " h";
  el("meta-speed").textContent = "速度 ×" + state.speed;
  const run = el("meta-running");
  run.textContent = state.running ? "运行中" : "已暂停";
  run.style.color = state.running ? "var(--good)" : "var(--warn)";
  el("btn-pause").textContent = state.running ? "⏸ 暂停" : "▶ 继续";
  el("btn-light").textContent = state.light ? "💡 关灯" : "💡 开灯";
  el("btn-filter").classList.toggle("active", state.filter_on);
  el("btn-filter").textContent = state.filter_on ? "🧹 过滤设备 开" : "🧹 过滤设备 关";
  el("water-volume").textContent = state.water_volume;
  el("water-capacity").textContent = state.capacity;

  // 速度滑块（拖动中不覆盖）
  if (!isDragging("slider-speed")) {
    el("slider-speed").value = state.speed;
    el("slider-speed-label").textContent = "速度 ×" + state.speed;
  }

  // ---- 温度模式 UI ----
  el("temp-current").textContent = state.temp;
  const isDaynight = state.temp_mode === "daynight";
  el("temp-panel-constant").style.display = isDaynight ? "none" : "";
  el("temp-panel-daynight").style.display = isDaynight ? "" : "none";
  el("btn-mode-constant").classList.toggle("active", !isDaynight);
  el("btn-mode-daynight").classList.toggle("active", isDaynight);

  if (!isDragging("slider-temp-set")) {
    el("slider-temp-set").value = state.temp_set;
    el("slider-temp-set-label").textContent = "目标温度 " + state.temp_set + "°C";
  }
  if (!isDragging("slider-temp-min")) {
    el("slider-temp-min").value = state.temp_min;
    el("slider-temp-min-label").textContent = "最低温 " + state.temp_min + "°C";
  }
  if (!isDragging("slider-temp-max")) {
    el("slider-temp-max").value = state.temp_max;
    el("slider-temp-max-label").textContent = "最高温 " + state.temp_max + "°C";
  }
  if (!isDragging("slider-day-hours")) {
    el("slider-day-hours").value = state.day_hours;
    el("slider-day-hours-label").textContent = "昼长 " + state.day_hours + "h";
  }
  if (!isDragging("slider-night-hours")) {
    el("slider-night-hours").value = state.night_hours;
    el("slider-night-hours-label").textContent = "夜长 " + state.night_hours + "h";
  }
}

function renderTrend(state) {
  const canvas = el("trend-chart");
  const ctx = canvas.getContext("2d");
  const hist = state.history || [];
  const W = canvas.width;
  const H = canvas.height;
  const padL = 40;
  const padR = 12;
  const padT = 12;
  const padB = 24;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;

  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = "#0f1830";
  ctx.fillRect(0, 0, W, H);

  // 网格 + Y 轴标签（0~最大值）
  ctx.strokeStyle = "#233450";
  ctx.fillStyle = "#7d8fb0";
  ctx.font = "11px sans-serif";
  ctx.lineWidth = 1;
  const yMax = 12;
  for (let i = 0; i <= 4; i++) {
    const y = padT + (plotH * i) / 4;
    const val = yMax - (yMax * i) / 4;
    ctx.beginPath();
    ctx.moveTo(padL, y);
    ctx.lineTo(W - padR, y);
    ctx.stroke();
    ctx.fillText(String(val), padL - 30, y + 4);
  }

  if (hist.length < 2) {
    ctx.fillStyle = "#7d8fb0";
    ctx.fillText("等待更多数据…", padL + 10, padT + 20);
    return;
  }

  const t0 = hist[0].time;
  const t1 = hist[hist.length - 1].time;
  const span = Math.max(t1 - t0, 0.001);

  const series = [
    { key: "oxygen", color: "#3aa0ff", label: "溶解氧" },
    { key: "ammonia", color: "#f0a202", label: "氨氮" },
    { key: "nitrate", color: "#2fbf71", label: "硝酸盐" },
  ];

  for (const s of series) {
    ctx.strokeStyle = s.color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    for (let i = 0; i < hist.length; i++) {
      const p = hist[i];
      const x = padL + ((p.time - t0) / span) * plotW;
      const y = padT + plotH * (1 - Math.min(p[s.key], yMax) / yMax);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }

  // X 轴标签（时间）
  ctx.fillStyle = "#7d8fb0";
  for (let i = 0; i <= 4; i++) {
    const x = padL + (plotW * i) / 4;
    const t = t0 + (span * i) / 4;
    ctx.fillText(t.toFixed(0) + "h", x - 12, H - 6);
  }

  // 图例
  let lx = padL;
  for (const s of series) {
    ctx.fillStyle = s.color;
    ctx.fillRect(lx, padT - 6, 10, 3);
    ctx.fillStyle = "#c4d2ea";
    ctx.fillText(s.label, lx + 14, padT - 4);
    lx += 14 + ctx.measureText(s.label).width + 22;
  }
}

function render(state) {
  currentState = state;
  renderHealth(state);
  renderPop(state);
  renderMetrics(state);
  renderMeta(state);
  renderTrend(state);
}

// ---------------- 数据刷新 ----------------
async function refresh() {
  try {
    const state = await fetchJSON(API_STATE);
    render(state);
  } catch (e) {
    // 服务未就绪时静默
  }
}

async function sendControl(action, value) {
  try {
    const state = await fetchJSON(API_CONTROL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: action, value: value }),
    });
    render(state);
  } catch (e) {
    console.error("control failed", e);
  }
}

// 绑定一个滑块：拖动时立即更新 label 取值、标记为拖动中、并发送控制；
// 松开（change）后取消标记，恢复轮询覆盖。
function bindDragSlider(sliderId, action, labelId, format) {
  const slider = el(sliderId);
  const label = el(labelId);
  slider.addEventListener("input", (e) => {
    const v = Number(e.target.value);
    draggingSliders.add(sliderId);
    if (label) label.textContent = format(v);
    sendControl(action, v);
  });
  slider.addEventListener("change", () => {
    draggingSliders.delete(sliderId);
  });
}

// 若某滑块正在被拖动，则跳过轮询对它的 value/label 覆盖，避免数字回弹。
function isDragging(sliderId) {
  return draggingSliders.has(sliderId);
}

// ---------------- 事件绑定 ----------------
function bindControls() {
  el("btn-pause").addEventListener("click", () => {
    if (currentState && currentState.running) sendControl("pause");
    else sendControl("resume");
  });
  el("btn-light").addEventListener("click", () => {
    if (currentState) sendControl("light", !currentState.light);
  });
  el("btn-reset").addEventListener("click", () => sendControl("reset"));
  el("btn-filter").addEventListener("click", () => {
    if (currentState) sendControl("filter", !currentState.filter_on);
  });
  el("btn-water").addEventListener("click", () => sendControl("add-water", 10));

  // 可调节数量的控件（喂食/加草/补菌/加鱼）：每个带 −/+ 步进器，一次加设定份数
  document.querySelectorAll(".adjust-item").forEach((item) => {
    const action = item.getAttribute("data-action");
    let count = 1; // 当前设定份数（每项独立记忆）
    const countEl = item.querySelector("[data-count]");
    const applyBtn = item.querySelector("[data-apply]");

    const renderCount = () => {
      countEl.textContent = String(count);
      applyBtn.textContent = "一次 +" + count + " 份";
    };

    item.querySelector('[data-adjust="minus"]').addEventListener("click", () => {
      if (count > 1) count -= 1;
      renderCount();
    });
    item.querySelector('[data-adjust="plus"]').addEventListener("click", () => {
      if (count < 99) count += 1;
      renderCount();
    });
    applyBtn.addEventListener("click", () => sendControl(action, count));

    renderCount();
  });

  // ---- 滑块（拖动即时更新，避免轮询回弹） ----
  bindDragSlider("slider-speed", "speed", "slider-speed-label", (v) => "速度 ×" + v);

  // ---- 温度模式 ----
  el("btn-mode-constant").addEventListener("click", () => sendControl("temp-mode", "constant"));
  el("btn-mode-daynight").addEventListener("click", () => sendControl("temp-mode", "daynight"));
  bindDragSlider("slider-temp-set", "temp-set", "slider-temp-set-label", (v) => "目标温度 " + v + "°C");
  bindDragSlider("slider-temp-min", "temp-min", "slider-temp-min-label", (v) => "最低温 " + v + "°C");
  bindDragSlider("slider-temp-max", "temp-max", "slider-temp-max-label", (v) => "最高温 " + v + "°C");
  bindDragSlider("slider-day-hours", "day-hours", "slider-day-hours-label", (v) => "昼长 " + v + "h");
  bindDragSlider("slider-night-hours", "night-hours", "slider-night-hours-label", (v) => "夜长 " + v + "h");
}

// ---------------- 启动 ----------------
window.addEventListener("DOMContentLoaded", () => {
  bindControls();
  refresh();
  setInterval(refresh, 1000);
});
