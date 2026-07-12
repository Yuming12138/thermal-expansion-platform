const api = async (path, options = {}) => {
  const response = await fetch(path, options);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || JSON.stringify(payload));
  return payload;
};

const show = (target, value) => {
  document.querySelector(target).textContent = JSON.stringify(value, null, 2);
};

const escapeHtml = value => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#39;");

const numeric = value => Number.isFinite(Number(value)) ? Number(value).toFixed(2) : "—";

const propertyText = property => {
  if (!property) return "—";
  const value = Number.isFinite(Number(property.value)) ? numeric(property.value) : String(property.value ?? "—");
  return escapeHtml(value + (property.unit ? " " + property.unit : ""));
};

async function loadStats() {
  const results = await Promise.all([api("/api/health"), api("/api/datasets/current")]);
  const dataset = results[1];
  document.querySelector("#health-status").textContent = "服务正常";
  const counts = dataset.counts;
  const cards = [
    ["活跃材料", counts.materials],
    ["结构文件", counts.structures],
    ["属性值", counts.property_values],
    ["数据版本", dataset.release.version],
  ];
  document.querySelector("#stats").innerHTML = cards.map(item =>
    "<article class='stat'><span>" + item[0] + "</span><strong>" + item[1] + "</strong></article>"
  ).join("");
}

function renderMaterials(items) {
  const container = document.querySelector("#material-results");
  if (!items.length) {
    container.innerHTML = "<p class='muted'>没有匹配材料。</p>";
    return;
  }
  const rows = items.map(item =>
    "<tr><td>" + escapeHtml(item.material_key) + "</td><td>" + numeric(item.G_GPa) +
    "</td><td>" + numeric(item.E_tilde_GPa) + "</td><td>" +
    numeric(item.CTE_ppm) + "</td><td><button data-key='" +
    escapeHtml(encodeURIComponent(item.material_key)) + "'>详情</button></td></tr>"
  ).join("");
  container.innerHTML = "<table><thead><tr><th>材料</th><th>G</th><th>Ẽ</th><th>CTE</th><th></th></tr></thead><tbody>" + rows + "</tbody></table>";
  container.querySelectorAll("button[data-key]").forEach(button => {
    button.addEventListener("click", () => loadDetail(decodeURIComponent(button.dataset.key)));
  });
}

async function searchMaterials() {
  const query = document.querySelector("#search-input").value;
  renderMaterials(await api("/api/materials?limit=50&query=" + encodeURIComponent(query)));
}

async function loadDetail(key) {
  const data = await api("/api/materials/" + encodeURIComponent(key));
  const structures = data.structures.map(s => s.format + " (" + s.content_characters + " chars)").join(", ");
  const metricNames = [
    "CTE_ppm", "TE_300K", "G_GPa", "E_tilde_GPa", "K_GPa",
    "E_coh_eV_per_atom", "avg_cn", "Band_Gap_eV", "NTE_temp_range",
  ];
  const metrics = metricNames
    .filter(name => data.properties[name])
    .map(name => "<div><dt>" + escapeHtml(name) + "</dt><dd>" +
      propertyText(data.properties[name]) + "</dd></div>")
    .join("");
  document.querySelector("#material-detail").innerHTML =
    "<p><strong>" + escapeHtml(data.material.material_key) + "</strong> · " +
    escapeHtml(data.material.external_id || "无外部ID") + "</p><p class='muted'>结构：" +
    escapeHtml(structures) + "</p><dl class='property-grid'>" + metrics +
    "</dl>" + renderPrecisionThermalExpansion(data.precision_thermal_expansion) +
    "<details><summary>查看全部数据字段</summary><pre>" +
    escapeHtml(JSON.stringify(data.properties, null, 2)) + "</pre></details>";
  drawPrecisionThermalExpansion(data.precision_thermal_expansion);
}

function renderPrecisionThermalExpansion(result) {
  if (!result || !result.points || result.points.length < 2) {
    return "<p class='muted'>暂无已关联的精确 QHA 热膨胀曲线。</p>";
  }
  const warnings = Array.isArray(result.quality_warnings) && result.quality_warnings.length
    ? "质量提示：" + result.quality_warnings.join("；")
    : "该曲线来自已关联的精确 QHA 任务。";
  return "<h3>精确 QHA 热膨胀曲线</h3><canvas id='thermal-curve' class='thermal-curve' width='520' height='250'></canvas>" +
    "<p class='curve-note'>任务 " + escapeHtml(result.job_id) + " · " + escapeHtml(warnings) + "</p>";
}

function drawPrecisionThermalExpansion(result) {
  if (!result || !result.points || result.points.length < 2) return;
  const canvas = document.querySelector("#thermal-curve");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const points = result.points
    .filter(point => Number.isFinite(Number(point.temperature_k)) && Number.isFinite(Number(point.alpha_ppm_per_k)))
    .map(point => ({...point, temperature_k: Number(point.temperature_k), alpha_ppm_per_k: Number(point.alpha_ppm_per_k)}));
  if (points.length < 2) return;
  const width = canvas.width;
  const height = canvas.height;
  const margin = {left: 54, right: 18, top: 18, bottom: 42};
  const xValues = points.map(point => point.temperature_k);
  const yValues = [...points.map(point => point.alpha_ppm_per_k), 0];
  const xSpan = Math.max(...xValues) - Math.min(...xValues) || 1;
  const ySpan = Math.max(...yValues) - Math.min(...yValues) || 1;
  const xMin = Math.max(0, Math.min(...xValues) - xSpan * .12);
  const xMax = Math.max(...xValues) + xSpan * .12;
  const yMin = Math.min(...yValues) - ySpan * .16;
  const yMax = Math.max(...yValues) + ySpan * .16;
  const x = value => margin.left + (value - xMin) / (xMax - xMin) * (width - margin.left - margin.right);
  const y = value => height - margin.bottom - (value - yMin) / (yMax - yMin) * (height - margin.top - margin.bottom);
  ctx.clearRect(0, 0, width, height);
  ctx.strokeStyle = "#b9c9d7";
  ctx.beginPath();
  ctx.moveTo(margin.left, margin.top);
  ctx.lineTo(margin.left, height - margin.bottom);
  ctx.lineTo(width - margin.right, height - margin.bottom);
  ctx.stroke();
  ctx.setLineDash([4, 4]);
  ctx.strokeStyle = "#d8e1ea";
  ctx.beginPath();
  ctx.moveTo(margin.left, y(0));
  ctx.lineTo(width - margin.right, y(0));
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.strokeStyle = "#1d6b83";
  ctx.lineWidth = 2;
  ctx.beginPath();
  points.forEach((point, index) => index ? ctx.lineTo(x(point.temperature_k), y(point.alpha_ppm_per_k)) : ctx.moveTo(x(point.temperature_k), y(point.alpha_ppm_per_k)));
  ctx.stroke();
  ctx.fillStyle = "#1d6b83";
  points.forEach(point => {
    ctx.beginPath();
    ctx.arc(x(point.temperature_k), y(point.alpha_ppm_per_k), 2.6, 0, Math.PI * 2);
    ctx.fill();
  });
  ctx.fillStyle = "#516476";
  ctx.font = "12px Segoe UI";
  for (let index = 0; index <= 4; index++) {
    const xValue = xMin + index / 4 * (xMax - xMin);
    const yValue = yMin + index / 4 * (yMax - yMin);
    ctx.fillText(xValue.toFixed(0), x(xValue) - 8, height - 23);
    ctx.fillText(yValue.toFixed(1), 4, y(yValue) + 4);
  }
  ctx.fillText("T (K)", width - 42, height - 7);
  ctx.save();
  ctx.translate(13, 100);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText("α (ppm/K)", 0, 0);
  ctx.restore();
}

function drawLandscape(points) {
  const canvas = document.querySelector("#landscape");
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  const margin = 44;
  ctx.clearRect(0, 0, width, height);
  const valid = points.filter(p => p.G_GPa > 0 && p.E_tilde_GPa > 0);
  const gLogs = valid.map(p => Math.log10(p.G_GPa));
  const eLogs = valid.map(p => Math.log10(p.E_tilde_GPa));
  const minG = Math.floor(Math.min(...gLogs));
  const maxG = Math.ceil(Math.max(...gLogs));
  const minE = Math.floor(Math.min(...eLogs));
  const maxE = Math.ceil(Math.max(...eLogs));
  const x = value => margin + (Math.log10(value) - minE) / Math.max(1, maxE - minE) * (width - margin - 24);
  const y = value => height - margin - (Math.log10(value) - minG) / Math.max(1, maxG - minG) * (height - margin - 24);
  ctx.strokeStyle = "#b9c9d7";
  ctx.beginPath();
  ctx.moveTo(margin, 12);
  ctx.lineTo(margin, height - margin);
  ctx.lineTo(width - 12, height - margin);
  ctx.stroke();
  valid.forEach(p => {
    const pointX = x(p.E_tilde_GPa);
    const pointY = y(p.G_GPa);
    ctx.fillStyle = p.G_GPa / p.E_tilde_GPa < 2.84 ? "rgba(36,119,181,.45)" : "rgba(215,111,50,.5)";
    ctx.beginPath();
    ctx.arc(pointX, pointY, 2.2, 0, Math.PI * 2);
    ctx.fill();
  });
  ctx.fillStyle = "#516476";
  ctx.font = "13px Segoe UI";
  for (let exponent = minE; exponent <= maxE; exponent++) {
    ctx.fillText("1e" + exponent, x(10 ** exponent) - 10, height - 25);
  }
  for (let exponent = minG; exponent <= maxG; exponent++) {
    ctx.fillText("1e" + exponent, 5, y(10 ** exponent) + 4);
  }
  ctx.fillText("Ẽ (GPa, log)", width - 116, height - 8);
  ctx.save();
  ctx.translate(15, 82);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText("G (GPa, log)", 0, 0);
  ctx.restore();
}

function postForm(formId, path, target, bodyBuilder) {
  document.querySelector(formId).addEventListener("submit", async event => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      show(target, await api(path, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(bodyBuilder(form)),
      }));
    } catch (error) {
      document.querySelector(target).textContent = error.message;
    }
  });
}

async function initialize() {
  try {
    await loadStats();
    await searchMaterials();
    drawLandscape(await api("/api/materials/landscape?limit=1600"));
  } catch (error) {
    document.querySelector("#health-status").textContent = "服务异常";
    console.error(error);
  }
  document.querySelector("#search-button").addEventListener("click", searchMaterials);
  postForm("#sbr-form", "/api/sbr/classify", "#sbr-result", form => ({
    shear_modulus_gpa: Number(form.get("g")),
    bonding_modulus_gpa: Number(form.get("e")),
  }));
  postForm("#fast-form", "/api/sbr/fast-screen", "#fast-result", form => ({
    predicted_shear_modulus_gpa: Number(form.get("g")),
    cohesive_energy_ev_per_atom: Number(form.get("ecoh")),
    cell_volume_a3: Number(form.get("volume")),
    atom_count: Number(form.get("atoms")),
    average_coordination_number: Number(form.get("cn")),
  }));
  postForm("#rom-form", "/api/composites/rom", "#rom-result", form => ({
    alpha_pte: Number(form.get("pte")),
    alpha_nte: Number(form.get("nte")),
    target_alpha: Number(form.get("target")),
  }));
  document.querySelector("#upload-form").addEventListener("submit", async event => {
    event.preventDefault();
    const file = document.querySelector("#structure-file").files[0];
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    try {
      show("#upload-result", await api("/api/structures/inspect", {method: "POST", body}));
    } catch (error) {
      document.querySelector("#upload-result").textContent = error.message;
    }
  });
  document.querySelector("#alignn-button").addEventListener("click", async () => {
    const file = document.querySelector("#structure-file").files[0];
    if (!file) {
      document.querySelector("#upload-result").textContent = "请先选择POSCAR或CIF文件。";
      return;
    }
    const body = new FormData();
    body.append("file", file);
    document.querySelector("#upload-result").textContent = "ALIGNN Worker计算中…";
    try {
      show("#upload-result", await api("/api/structures/alignn-shear", {method: "POST", body}));
    } catch (error) {
      document.querySelector("#upload-result").textContent = error.message;
    }
  });
  document.querySelector("#fast-screen-button").addEventListener("click", async () => {
    const file = document.querySelector("#structure-file").files[0];
    if (!file) {
      document.querySelector("#upload-result").textContent = "请先选择POSCAR或CIF文件。";
      return;
    }
    const body = new FormData();
    body.append("file", file);
    document.querySelector("#upload-result").textContent = "正在计算 ALIGNN、MatterSim 与 CrystalNN…";
    try {
      show("#upload-result", await api("/api/structures/fast-screen", {method: "POST", body}));
    } catch (error) {
      document.querySelector("#upload-result").textContent = error.message;
    }
  });
  document.querySelector("#precision-button").addEventListener("click", async () => {
    const file = document.querySelector("#structure-file").files[0];
    if (!file) {
      document.querySelector("#upload-result").textContent = "请先选择POSCAR或CIF文件。";
      return;
    }
    const body = new FormData();
    body.append("file", file);
    document.querySelector("#upload-result").textContent = "精确任务已提交，正在等待后台Worker…";
    try {
      const job = await api("/api/precision/jobs", {method: "POST", body});
      show("#upload-result", job);
      const poll = async () => {
        const latest = await api("/api/precision/jobs/" + encodeURIComponent(job.id));
        show("#upload-result", latest);
        if (["PENDING", "QUEUED", "RUNNING"].includes(latest.status)) {
          window.setTimeout(() => poll().catch(error => {
            document.querySelector("#upload-result").textContent = error.message;
          }), 3000);
        }
      };
      window.setTimeout(() => poll().catch(error => {
        document.querySelector("#upload-result").textContent = error.message;
      }), 1000);
    } catch (error) {
      document.querySelector("#upload-result").textContent = error.message;
    }
  });
  document.querySelector("#agent-form").addEventListener("submit", async event => {
    event.preventDefault();
    const message = document.querySelector("#agent-message").value;
    try {
      show("#agent-result", await api("/api/agent/chat", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({message}),
      }));
    } catch (error) {
      document.querySelector("#agent-result").textContent = error.message;
    }
  });
}

initialize();
