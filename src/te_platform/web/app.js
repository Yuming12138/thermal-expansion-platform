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

let fig1dReference = null;
let selectedLandscapePoint = null;
let landscapeHitPoints = [];
let agentHistory = [];
const LANDSCAPE_MARKER_SIZE = 3.6;

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
  selectLandscapeMaterial(data);
}

function selectLandscapeMaterial(data) {
  const value = name => Number(data.properties[name]?.value);
  const shear = value("G_GPa");
  const cohesive = value("E_coh_eV_per_atom");
  const atomicVolume = value("AAV");
  const coordination = value("avg_cn");
  const cte = value("CTE_ppm");
  if (![shear, cohesive, atomicVolume, coordination].every(Number.isFinite) ||
      shear <= 0 || atomicVolume <= 0 || coordination <= 0) {
    selectedLandscapePoint = null;
    document.querySelector("#landscape-selection").textContent =
      "该材料缺少 Fig. 1d 坐标所需的 G、E_coh、AAV 或 avg_cn。";
    drawLandscape();
    return;
  }
  selectedLandscapePoint = {
    material_key: data.material.material_key,
    x_gpa: 160.217 * Math.abs(cohesive) / (atomicVolume * coordination),
    g_gpa: shear,
    classification: Number.isFinite(cte) && cte < 0 ? "NTE" : "PTE",
    source: "当前数据库",
    year: null,
    selected: true,
  };
  document.querySelector("#landscape-selection").textContent =
    "当前材料：" + data.material.material_key + " · Ẽ=" +
    selectedLandscapePoint.x_gpa.toFixed(3) + " GPa · G=" + shear.toFixed(3) + " GPa";
  drawLandscape();
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

function drawPrecisionThermalExpansion(result, canvasSelector = "#thermal-curve") {
  if (!result || !result.points || result.points.length < 2) return;
  const canvas = document.querySelector(canvasSelector);
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

function rgba(hex, opacity) {
  const value = hex.replace("#", "");
  const red = parseInt(value.slice(0, 2), 16);
  const green = parseInt(value.slice(2, 4), 16);
  const blue = parseInt(value.slice(4, 6), 16);
  return "rgba(" + red + "," + green + "," + blue + "," + opacity + ")";
}

function drawLandscapeMarker(ctx, point, x, y, size, color) {
  ctx.fillStyle = color;
  ctx.strokeStyle = "rgba(255,255,255,.86)";
  ctx.lineWidth = .8;
  ctx.beginPath();
  if (point.source === "DFT") {
    const halfSide = size * Math.sqrt(Math.PI) / 2;
    ctx.rect(x - halfSide, y - halfSide, halfSide * 2, halfSide * 2);
  } else if (point.source === "our" || point.source === "This work") {
    const diamondRadius = size * Math.sqrt(Math.PI / 2);
    ctx.moveTo(x, y - diamondRadius);
    ctx.lineTo(x + diamondRadius, y);
    ctx.lineTo(x, y + diamondRadius);
    ctx.lineTo(x - diamondRadius, y);
    ctx.closePath();
  } else {
    ctx.arc(x, y, size, 0, Math.PI * 2);
  }
  ctx.fill();
  ctx.stroke();
}

function drawSelectedStar(ctx, x, y) {
  ctx.save();
  ctx.fillStyle = "#d7191c";
  ctx.strokeStyle = "#fff";
  ctx.lineWidth = 2.2;
  ctx.beginPath();
  for (let index = 0; index < 10; index++) {
    const radius = index % 2 ? 5 : 11;
    const angle = -Math.PI / 2 + index * Math.PI / 5;
    const px = x + Math.cos(angle) * radius;
    const py = y + Math.sin(angle) * radius;
    index ? ctx.lineTo(px, py) : ctx.moveTo(px, py);
  }
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
  ctx.restore();
}

function drawLandscape() {
  if (!fig1dReference) return;
  const canvas = document.querySelector("#landscape");
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  const margin = {left: 72, right: 22, top: 18, bottom: 64};
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const axis = fig1dReference.axis;
  const points = fig1dReference.points;
  const logXMin = Math.log10(axis.x_min);
  const logXMax = Math.log10(axis.x_max);
  const logYMin = Math.log10(axis.y_min);
  const logYMax = Math.log10(axis.y_max);
  const x = value => margin.left + (Math.log10(value) - logXMin) / (logXMax - logXMin) * plotWidth;
  const y = value => margin.top + (logYMax - Math.log10(value)) / (logYMax - logYMin) * plotHeight;
  ctx.clearRect(0, 0, width, height);

  const gradientData = fig1dReference.gradient;
  const gradient = ctx.createLinearGradient(
    margin.left + gradientData.start[0] * plotWidth,
    margin.top + gradientData.start[1] * plotHeight,
    margin.left + gradientData.end[0] * plotWidth,
    margin.top + gradientData.end[1] * plotHeight,
  );
  gradientData.stops.forEach(stop => gradient.addColorStop(stop[0], rgba(stop[1], stop[2])));
  ctx.fillStyle = gradient;
  ctx.fillRect(margin.left, margin.top, plotWidth, plotHeight);

  ctx.save();
  ctx.beginPath();
  ctx.rect(margin.left, margin.top, plotWidth, plotHeight);
  ctx.clip();
  const boundaryX0 = Math.max(axis.x_min, axis.y_min / axis.boundary_c);
  const boundaryX1 = Math.min(axis.x_max, axis.y_max / axis.boundary_c);
  ctx.setLineDash([8, 5]);
  ctx.strokeStyle = "rgba(20,30,42,.88)";
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(x(boundaryX0), y(axis.boundary_c * boundaryX0));
  ctx.lineTo(x(boundaryX1), y(axis.boundary_c * boundaryX1));
  ctx.stroke();
  ctx.setLineDash([]);

  landscapeHitPoints = [];
  points.forEach(point => {
    if (point.x_gpa < axis.x_min || point.x_gpa > axis.x_max ||
        point.g_gpa < axis.y_min || point.g_gpa > axis.y_max) return;
    const pointX = x(point.x_gpa);
    const pointY = y(point.g_gpa);
    const color = point.classification === "NTE" ? "rgba(68,119,170,.78)" : "rgba(253,56,39,.72)";
    drawLandscapeMarker(ctx, point, pointX, pointY, LANDSCAPE_MARKER_SIZE, color);
    landscapeHitPoints.push({...point, canvasX: pointX, canvasY: pointY});
  });

  if (selectedLandscapePoint && selectedLandscapePoint.x_gpa >= axis.x_min &&
      selectedLandscapePoint.x_gpa <= axis.x_max && selectedLandscapePoint.g_gpa >= axis.y_min &&
      selectedLandscapePoint.g_gpa <= axis.y_max) {
    const selectedX = x(selectedLandscapePoint.x_gpa);
    const selectedY = y(selectedLandscapePoint.g_gpa);
    drawSelectedStar(ctx, selectedX, selectedY);
    landscapeHitPoints.unshift({...selectedLandscapePoint, canvasX: selectedX, canvasY: selectedY});
  }
  ctx.restore();

  ctx.strokeStyle = "#2b3642";
  ctx.lineWidth = 1.2;
  ctx.strokeRect(margin.left, margin.top, plotWidth, plotHeight);
  ctx.fillStyle = "#3f4e5e";
  ctx.font = "14px Segoe UI";
  ctx.textAlign = "center";
  [5, 10, 20, 50].forEach(value => {
    ctx.beginPath();
    ctx.moveTo(x(value), margin.top + plotHeight);
    ctx.lineTo(x(value), margin.top + plotHeight + 6);
    ctx.stroke();
    ctx.fillText(String(value), x(value), height - 35);
  });
  ctx.textAlign = "right";
  [1, 10, 100].forEach(value => {
    ctx.beginPath();
    ctx.moveTo(margin.left - 6, y(value));
    ctx.lineTo(margin.left, y(value));
    ctx.stroke();
    ctx.fillText(value === 1 ? "10⁰" : value === 10 ? "10¹" : "10²", margin.left - 10, y(value) + 5);
  });
  ctx.textAlign = "center";
  ctx.fillText("Ẽ = 160.217|E_coh|/(AAV·CN) (GPa)", margin.left + plotWidth / 2, height - 9);
  ctx.save();
  ctx.translate(18, margin.top + plotHeight / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText("G (GPa)", 0, 0);
  ctx.restore();

  ctx.textAlign = "left";
  ctx.font = "13px Segoe UI";
  const legendX = margin.left + plotWidth - 195;
  const legendY = margin.top + plotHeight - 42;
  drawLandscapeMarker(ctx, {source: "Exp."}, legendX, legendY, LANDSCAPE_MARKER_SIZE, "rgba(68,119,170,.9)");
  ctx.fillText("NTE", legendX + 10, legendY + 4);
  drawLandscapeMarker(ctx, {source: "DFT"}, legendX + 62, legendY, LANDSCAPE_MARKER_SIZE, "rgba(253,56,39,.85)");
  ctx.fillText("PTE", legendX + 72, legendY + 4);
  drawSelectedStar(ctx, legendX + 130, legendY);
  ctx.fillText("当前材料", legendX + 144, legendY + 4);
}

function setupLandscapeInteraction() {
  const canvas = document.querySelector("#landscape");
  const tooltip = document.querySelector("#landscape-tooltip");
  const wrap = document.querySelector(".landscape-wrap");
  canvas.addEventListener("mousemove", event => {
    const rect = canvas.getBoundingClientRect();
    const canvasX = (event.clientX - rect.left) * canvas.width / rect.width;
    const canvasY = (event.clientY - rect.top) * canvas.height / rect.height;
    let nearest = null;
    let nearestDistance = Infinity;
    landscapeHitPoints.forEach(point => {
      const distance = Math.hypot(point.canvasX - canvasX, point.canvasY - canvasY);
      if (distance < nearestDistance) {
        nearestDistance = distance;
        nearest = point;
      }
    });
    if (!nearest || nearestDistance > 13) {
      tooltip.hidden = true;
      return;
    }
    tooltip.innerHTML = "<strong>" + escapeHtml(nearest.material_key) + "</strong><br>" +
      escapeHtml(nearest.classification) + " · " + escapeHtml(nearest.source || "—") +
      (nearest.year ? " · " + nearest.year : "") + "<br>Ẽ=" + nearest.x_gpa.toFixed(3) +
      " GPa · G=" + nearest.g_gpa.toFixed(3) + " GPa";
    tooltip.hidden = false;
    const left = Math.min(event.clientX - rect.left + 14, wrap.clientWidth - tooltip.offsetWidth - 8);
    const top = Math.max(8, event.clientY - rect.top - tooltip.offsetHeight - 10);
    tooltip.style.left = Math.max(8, left) + "px";
    tooltip.style.top = top + "px";
  });
  canvas.addEventListener("mouseleave", () => { tooltip.hidden = true; });
}

function uploadedStructure() {
  return document.querySelector("#structure-file").files[0] || null;
}

function structureBody(file) {
  const body = new FormData();
  body.append("file", file);
  return body;
}

function setPredictionButtonsDisabled(disabled) {
  ["#fast-screen-button", "#elastic-button", "#qha-button"].forEach(selector => {
    document.querySelector(selector).disabled = disabled;
  });
}

function classificationText(value) {
  return {
    high_probability_nte: "高概率 NTE",
    nte: "NTE 候选",
    pte: "PTE",
    boundary: "分界附近",
  }[value] || value || "—";
}

function metricCards(items) {
  return "<div class='prediction-metrics'>" + items.map(item =>
    "<div><span>" + escapeHtml(item[0]) + "</span><strong" +
    (item[2] ? " id='" + escapeHtml(item[2]) + "'" : "") + ">" +
    escapeHtml(item[1]) + "</strong></div>"
  ).join("") + "</div>";
}

function selectPredictedLandscapePoint(filename, shear, bonding, classification, source) {
  selectedLandscapePoint = {
    material_key: filename,
    x_gpa: Number(bonding),
    g_gpa: Number(shear),
    classification: String(classification).includes("pte") && !String(classification).includes("nte") ? "PTE" : "NTE",
    source,
    year: null,
    selected: true,
  };
  document.querySelector("#landscape-selection").textContent =
    "当前预测：" + filename + " · Ẽ=" + Number(bonding).toFixed(3) +
    " GPa · G=" + Number(shear).toFixed(3) + " GPa";
  drawLandscape();
}

function renderFastPrediction(file, payload) {
  const result = payload.fast_sbr;
  const sbr = result.sbr;
  const bonding = result.bonding;
  document.querySelector("#prediction-result").innerHTML =
    "<h3>快速预测结果</h3>" + metricCards([
      ["ALIGNN 剪切模量 G", numeric(result.predicted_shear_modulus_gpa) + " GPa"],
      ["MatterSim 键合模量 Ẽ", numeric(bonding.bonding_modulus_gpa) + " GPa"],
      ["剪切—键合比 ξ", Number(sbr.xi).toFixed(4)],
      ["预测结论", classificationText(sbr.classification)],
    ]) + "<p class='curve-note'>置信等级：" + escapeHtml(result.decision_quality) +
    "；建议：" + escapeHtml(result.recommended_next_step) + "</p>";
  selectPredictedLandscapePoint(
    file.name,
    result.predicted_shear_modulus_gpa,
    bonding.bonding_modulus_gpa,
    sbr.classification,
    "快速预测",
  );
}

function tensorTable(tensor) {
  if (!Array.isArray(tensor) || tensor.length !== 6) return "";
  return "<table class='tensor-table'><tbody>" + tensor.map(row =>
    "<tr>" + row.map(value => "<td>" + Number(value).toFixed(3) + "</td>").join("") + "</tr>"
  ).join("") + "</tbody></table>";
}

function renderElasticPrediction(file, result) {
  const sbr = result.sbr;
  const bonding = result.bonding;
  document.querySelector("#prediction-result").innerHTML =
    "<h3>精准弹性预测结果</h3>" + metricCards([
      ["Hill 剪切模量 G", numeric(result.shear_modulus_hill_gpa) + " GPa"],
      ["MatterSim 键合模量 Ẽ", numeric(bonding.bonding_modulus_gpa) + " GPa"],
      ["剪切—键合比 ξ", Number(sbr.xi).toFixed(4)],
      ["预测结论", classificationText(sbr.classification)],
    ]) + "<h3>完整弹性张量 Cᵢⱼ (GPa)</h3>" + tensorTable(result.elastic_tensor_gpa) +
    (result.quality_warnings?.length ? "<p class='curve-note'>质量提示：" +
      escapeHtml(result.quality_warnings.join("；")) + "</p>" : "");
  selectPredictedLandscapePoint(
    file.name,
    result.shear_modulus_hill_gpa,
    bonding.bonding_modulus_gpa,
    sbr.classification,
    "精准弹性预测",
  );
}

function renderQhaPrediction(result) {
  document.querySelector("#prediction-result").innerHTML =
    "<h3>QHA 热膨胀结果</h3>" + metricCards([
      ["300 K 热膨胀系数", numeric(result.alpha_300k_ppm_per_k) + " ppm/K"],
      ["温度点数", String(result.thermal_expansion_curve?.length || 0)],
      ["计算模式", "MatterSim QHA"],
      ["结果状态", "计算完成"],
    ]) + "<canvas id='prediction-thermal-curve' class='prediction-thermal-curve' width='900' height='360'></canvas>" +
    (result.quality_warnings?.length ? "<p class='curve-note'>质量提示：" +
      escapeHtml(result.quality_warnings.join("；")) + "</p>" : "");
  drawPrecisionThermalExpansion(
    {points: result.thermal_expansion_curve.map(point => ({temperature_k: point[0], alpha_ppm_per_k: point[1] * 1_000_000}))},
    "#prediction-thermal-curve",
  );
}

function renderJobProgress(job, label) {
  const progress = job.progress || {};
  const progressText = Number.isFinite(Number(progress.percent)) ? " · " + progress.percent + "%" : "";
  document.querySelector("#prediction-result").innerHTML =
    "<h3>" + escapeHtml(label) + "</h3><p>任务 " + escapeHtml(job.id) +
    " · " + escapeHtml(job.status) + progressText + "</p>";
}

async function pollPredictionJob(jobId, mode, file) {
  try {
    const job = await api("/api/precision/jobs/" + encodeURIComponent(jobId));
    renderJobProgress(job, mode === "elastic" ? "精准弹性计算中" : "QHA 计算中");
    if (["PENDING", "QUEUED", "RUNNING"].includes(job.status)) {
      window.setTimeout(() => pollPredictionJob(jobId, mode, file), 3000);
      return;
    }
    setPredictionButtonsDisabled(false);
    if (job.status !== "SUCCEEDED") {
      document.querySelector("#prediction-result").innerHTML =
        "<h3>计算失败</h3><p>" + escapeHtml(job.error_message || "请查看任务日志。") + "</p>";
      return;
    }
    if (mode === "elastic") renderElasticPrediction(file, job.result);
    else renderQhaPrediction(job.result);
  } catch (error) {
    setPredictionButtonsDisabled(false);
    document.querySelector("#prediction-result").textContent = error.message;
  }
}

async function submitPredictionJob(endpoint, mode) {
  const file = uploadedStructure();
  if (!file) {
    document.querySelector("#prediction-result").textContent = "请先选择 CIF 或 POSCAR 文件。";
    return;
  }
  setPredictionButtonsDisabled(true);
  document.querySelector("#prediction-result").textContent = mode === "elastic"
    ? "正在提交完整弹性张量计算…" : "正在提交 MatterSim QHA 计算…";
  try {
    const job = await api(endpoint, {method: "POST", body: structureBody(file)});
    renderJobProgress(job, mode === "elastic" ? "精准弹性任务已提交" : "QHA 任务已提交");
    window.setTimeout(() => pollPredictionJob(job.id, mode, file), 800);
  } catch (error) {
    setPredictionButtonsDisabled(false);
    document.querySelector("#prediction-result").textContent = error.message;
  }
}

async function loadCompositeMaterials(role) {
  const search = document.querySelector("#" + role + "-search").value;
  const select = document.querySelector("#" + role + "-material");
  const materials = await api(
    "/api/composites/materials?role=" + role + "&limit=50&query=" + encodeURIComponent(search)
  );
  select.innerHTML = materials.map(material =>
    "<option value='" + escapeHtml(material.material_key) + "'>" +
    escapeHtml(role === "pte" ? (material.formula || material.material_key) : material.material_key) +
    " · α₃₀₀=" + numeric(material.alpha_300k_ppm_per_k) + " ppm/K</option>"
  ).join("");
  if (!materials.length) {
    select.innerHTML = "<option value=''>没有匹配且带完整曲线的材料</option>";
  }
  return materials;
}

function drawZteCurves(result) {
  const canvas = document.querySelector("#zte-curve");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  const margin = {left: 64, right: 24, top: 24, bottom: 50};
  const temperatures = result.temperatures_k.map(Number);
  const pte = result.pte_alpha_ppm_per_k.map(Number);
  const nte = result.nte_alpha_ppm_per_k.map(Number);
  const mixed = result.mixed_alpha_ppm_per_k.map(Number);
  const target = Number(result.target_alpha_ppm_per_k);
  const zteLimit = 5;
  const allY = [...pte, ...nte, ...mixed, target, -zteLimit, zteLimit];
  const xMin = 0;
  const xMax = 1000;
  const rawYMin = Math.min(...allY);
  const rawYMax = Math.max(...allY);
  const yPad = Math.max((rawYMax - rawYMin) * .12, 1);
  const yMin = rawYMin - yPad;
  const yMax = rawYMax + yPad;
  const x = value => margin.left + (value - xMin) / (xMax - xMin || 1) * (width - margin.left - margin.right);
  const y = value => height - margin.bottom - (value - yMin) / (yMax - yMin || 1) * (height - margin.top - margin.bottom);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "rgba(22, 131, 106, 0.14)";
  ctx.fillRect(
    margin.left,
    y(zteLimit),
    width - margin.left - margin.right,
    y(-zteLimit) - y(zteLimit)
  );
  ctx.setLineDash([4, 4]);
  ctx.strokeStyle = "rgba(22, 131, 106, 0.72)";
  ctx.lineWidth = 1;
  for (const limit of [-zteLimit, zteLimit]) {
    ctx.beginPath();
    ctx.moveTo(margin.left, y(limit));
    ctx.lineTo(width - margin.right, y(limit));
    ctx.stroke();
  }
  ctx.setLineDash([]);
  for (let value = 0; value <= 1000; value += 100) {
    ctx.strokeStyle = "rgba(174, 189, 202, 0.32)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x(value), margin.top);
    ctx.lineTo(x(value), height - margin.bottom);
    ctx.stroke();
  }
  ctx.strokeStyle = "#aebdca";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(margin.left, margin.top);
  ctx.lineTo(margin.left, height - margin.bottom);
  ctx.lineTo(width - margin.right, height - margin.bottom);
  ctx.stroke();
  ctx.setLineDash([6, 5]);
  ctx.strokeStyle = "#2b3642";
  ctx.beginPath();
  ctx.moveTo(margin.left, y(target));
  ctx.lineTo(width - margin.right, y(target));
  ctx.stroke();
  ctx.setLineDash([]);
  const drawLine = (values, color, widthValue) => {
    ctx.strokeStyle = color;
    ctx.lineWidth = widthValue;
    ctx.beginPath();
    values.forEach((value, index) => index
      ? ctx.lineTo(x(temperatures[index]), y(value))
      : ctx.moveTo(x(temperatures[index]), y(value)));
    ctx.stroke();
  };
  drawLine(pte, "#fd3827", 1.8);
  drawLine(nte, "#4477aa", 1.8);
  drawLine(mixed, "#16836a", 3.0);
  ctx.fillStyle = "#516476";
  ctx.font = "12px Segoe UI";
  ctx.textAlign = "center";
  for (let value = 0; value <= 1000; value += 100) {
    ctx.fillStyle = "#516476";
    ctx.fillText(String(value), x(value), height - 26);
  }
  ctx.textAlign = "right";
  for (let index = 0; index <= 4; index++) {
    const value = yMin + index / 4 * (yMax - yMin);
    ctx.fillText(value.toFixed(1), margin.left - 8, y(value) + 4);
  }
  ctx.textAlign = "center";
  ctx.fillText("温度 (K)", margin.left + (width - margin.left - margin.right) / 2, height - 6);
  ctx.save();
  ctx.translate(15, margin.top + (height - margin.top - margin.bottom) / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText("α (ppm/K)", 0, 0);
  ctx.restore();
  ctx.textAlign = "left";
  const legendY = 18;
  [["PTE", "#fd3827"], ["NTE", "#4477aa"], ["混合", "#16836a"]].forEach((item, index) => {
    const startX = margin.left + index * 78;
    ctx.strokeStyle = item[1];
    ctx.lineWidth = item[0] === "混合" ? 3 : 2;
    ctx.beginPath();
    ctx.moveTo(startX, legendY);
    ctx.lineTo(startX + 20, legendY);
    ctx.stroke();
    ctx.fillStyle = "#516476";
    ctx.fillText(item[0], startX + 25, legendY + 4);
  });
  const bandLegendX = margin.left + 245;
  ctx.fillStyle = "rgba(22, 131, 106, 0.18)";
  ctx.fillRect(bandLegendX, legendY - 7, 20, 10);
  ctx.strokeStyle = "rgba(22, 131, 106, 0.72)";
  ctx.strokeRect(bandLegendX, legendY - 7, 20, 10);
  ctx.fillStyle = "#516476";
  ctx.fillText("ZTE ±5 ppm/K", bandLegendX + 25, legendY + 4);
}

function renderZteDesign(result) {
  const ntePercent = Number(result.nte_volume_fraction) * 100;
  const ptePercent = 100 - ntePercent;
  document.querySelector("#zte-result").innerHTML =
    "<h3>曲线配比优化结果</h3>" + metricCards([
      ["PTE 体积分数", ptePercent.toFixed(2) + "%", "zte-pte-fraction"],
      ["NTE 体积分数", ntePercent.toFixed(2) + "%", "zte-nte-fraction"],
      ["温区 RMS 偏差", numeric(result.rms_error_ppm_per_k) + " ppm/K", "zte-rms"],
      ["最大绝对偏差", numeric(result.max_absolute_error_ppm_per_k) + " ppm/K", "zte-max-error"],
    ]) + "<p class='curve-note'>PTE：" + escapeHtml(result.pte_material.formula || result.pte_material.material_key) +
    "；NTE：" + escapeHtml(result.nte_material.material_key) + "；优化温区：" +
    numeric(result.temperature_min_k) + "–" + numeric(result.temperature_max_k) +
    " K；完整曲线：" + numeric(result.curve_temperature_min_k) + "–" +
    numeric(result.curve_temperature_max_k) + " K</p>" +
    "<div class='zte-fraction-control'><div class='zte-fraction-heading'>" +
    "<strong>NTE 掺杂浓度</strong><span>算法最佳：" + ntePercent.toFixed(2) + "%</span>" +
    "<button id='zte-reset-fraction' type='button'>恢复最佳比例</button></div>" +
    "<div class='zte-slider-wrap'><input id='zte-fraction-slider' type='range' min='0' max='100' step='0.01' " +
    "value='" + ntePercent.toFixed(2) + "' aria-label='NTE 掺杂浓度百分比'>" +
    "<span class='zte-best-marker' style='left:" + ntePercent.toFixed(3) +
    "%' title='算法最佳比例 " + ntePercent.toFixed(2) + "%'></span></div>" +
    "<div class='zte-slider-scale'><span>0% NTE</span><strong id='zte-current-fraction'>当前：" +
    ntePercent.toFixed(1) + "% NTE</strong><span>100% NTE</span></div></div>" +
    "<canvas id='zte-curve' class='zte-curve' width='1000' height='420'></canvas>";
  const slider = document.querySelector("#zte-fraction-slider");
  const applyFraction = value => {
    const fraction = Math.min(1, Math.max(0, Number(value) / 100));
    const pte = result.pte_alpha_ppm_per_k.map(Number);
    const nte = result.nte_alpha_ppm_per_k.map(Number);
    const mixed = pte.map((pteValue, index) =>
      (1 - fraction) * pteValue + fraction * nte[index]
    );
    const errors = mixed.filter((_, index) => {
      const temperature = Number(result.temperatures_k[index]);
      return temperature >= Number(result.temperature_min_k) &&
        temperature <= Number(result.temperature_max_k);
    }).map(value => value - Number(result.target_alpha_ppm_per_k));
    const rms = Math.sqrt(errors.reduce((total, value) => total + value * value, 0) / errors.length);
    const maxError = Math.max(...errors.map(Math.abs));
    document.querySelector("#zte-pte-fraction").textContent = ((1 - fraction) * 100).toFixed(2) + "%";
    document.querySelector("#zte-nte-fraction").textContent = (fraction * 100).toFixed(2) + "%";
    document.querySelector("#zte-rms").textContent = numeric(rms) + " ppm/K";
    document.querySelector("#zte-max-error").textContent = numeric(maxError) + " ppm/K";
    document.querySelector("#zte-current-fraction").textContent =
      "当前：" + (fraction * 100).toFixed(1) + "% NTE";
    drawZteCurves({...result, mixed_alpha_ppm_per_k: mixed, nte_volume_fraction: fraction});
  };
  slider.addEventListener("input", () => applyFraction(slider.value));
  document.querySelector("#zte-reset-fraction").addEventListener("click", () => {
    slider.value = ntePercent.toFixed(2);
    applyFraction(slider.value);
  });
  drawZteCurves(result);
}

async function designZteComposite() {
  const pteKey = document.querySelector("#pte-material").value;
  const nteKey = document.querySelector("#nte-material").value;
  if (!pteKey || !nteKey) {
    document.querySelector("#zte-result").textContent = "请先选择 PTE 和 NTE 材料。";
    return;
  }
  document.querySelector("#zte-design-button").disabled = true;
  document.querySelector("#zte-result").textContent = "正在读取两条真实 QHA 曲线并优化配比…";
  try {
    const result = await api("/api/composites/curve-design", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        pte_material_key: pteKey,
        nte_material_key: nteKey,
        temperature_min_k: Number(document.querySelector("#zte-t-min").value),
        temperature_max_k: Number(document.querySelector("#zte-t-max").value),
        target_alpha_ppm_per_k: Number(document.querySelector("#zte-target").value),
      }),
    });
    renderZteDesign(result);
  } catch (error) {
    document.querySelector("#zte-result").textContent = error.message;
  } finally {
    document.querySelector("#zte-design-button").disabled = false;
  }
}

async function initialize() {
  try {
    const results = await Promise.all([
      loadStats(),
      searchMaterials(),
      api("/static/fig1d-reference.json"),
    ]);
    fig1dReference = results[2];
    drawLandscape();
  } catch (error) {
    document.querySelector("#health-status").textContent = "服务异常";
    console.error(error);
  }
  setupLandscapeInteraction();
  document.querySelector("#search-button").addEventListener("click", searchMaterials);
  document.querySelector("#pte-search-button").addEventListener("click", () =>
    loadCompositeMaterials("pte").catch(error => { document.querySelector("#zte-result").textContent = error.message; }));
  document.querySelector("#nte-search-button").addEventListener("click", () =>
    loadCompositeMaterials("nte").catch(error => { document.querySelector("#zte-result").textContent = error.message; }));
  document.querySelector("#zte-design-button").addEventListener("click", designZteComposite);
  Promise.all([loadCompositeMaterials("pte"), loadCompositeMaterials("nte")])
    .then(() => { document.querySelector("#zte-result").textContent = "请选择材料和目标温区，然后优化配比。"; })
    .catch(error => { document.querySelector("#zte-result").textContent = error.message; });
  document.querySelector("#structure-file").addEventListener("change", async () => {
    const file = uploadedStructure();
    if (!file) return;
    document.querySelector("#structure-summary").textContent = "正在检查结构…";
    try {
      const result = await api("/api/structures/inspect", {method: "POST", body: structureBody(file)});
      const inspection = result.inspection;
      document.querySelector("#structure-summary").textContent =
        file.name + " · " + inspection.format.toUpperCase() + " · " +
        (inspection.atom_count ?? "待解析") + " atoms · " +
        (Number.isFinite(Number(inspection.cell_volume_a3)) ? Number(inspection.cell_volume_a3).toFixed(3) + " Å³" : "体积待解析");
      document.querySelector("#prediction-result").textContent = "结构检查完成，请选择计算层级。";
    } catch (error) {
      document.querySelector("#structure-summary").textContent = error.message;
    }
  });
  document.querySelector("#fast-screen-button").addEventListener("click", async () => {
    const file = uploadedStructure();
    if (!file) {
      document.querySelector("#prediction-result").textContent = "请先选择 CIF 或 POSCAR 文件。";
      return;
    }
    setPredictionButtonsDisabled(true);
    document.querySelector("#prediction-result").textContent = "正在运行 ALIGNN、MatterSim 与 CrystalNN…";
    try {
      renderFastPrediction(file, await api("/api/structures/fast-screen", {method: "POST", body: structureBody(file)}));
    } catch (error) {
      document.querySelector("#prediction-result").textContent = error.message;
    } finally {
      setPredictionButtonsDisabled(false);
    }
  });
  document.querySelector("#elastic-button").addEventListener("click", () =>
    submitPredictionJob("/api/precision/elastic-jobs", "elastic"));
  document.querySelector("#qha-button").addEventListener("click", () =>
    submitPredictionJob("/api/precision/qha-jobs", "qha"));
  const agentWidget = document.querySelector("#agent-widget");
  const agentToggle = document.querySelector("#agent-toggle");
  agentToggle.addEventListener("click", () => {
    const collapsed = agentWidget.classList.toggle("collapsed");
    agentToggle.textContent = collapsed ? "+" : "−";
    agentToggle.setAttribute("aria-expanded", String(!collapsed));
    agentToggle.setAttribute("aria-label", collapsed ? "展开 Agent" : "最小化 Agent");
  });

  function appendAgentMessage(role, text, extraClass = "") {
    const bubble = document.createElement("div");
    bubble.className = `agent-bubble ${role} ${extraClass}`.trim();
    bubble.textContent = text;
    const messages = document.querySelector("#agent-messages");
    messages.appendChild(bubble);
    messages.scrollTop = messages.scrollHeight;
    return bubble;
  }

  document.querySelector("#agent-form").addEventListener("submit", async event => {
    event.preventDefault();
    const input = document.querySelector("#agent-message");
    const sendButton = document.querySelector("#agent-send");
    const message = input.value.trim();
    if (!message) return;
    appendAgentMessage("user", message);
    input.value = "";
    sendButton.disabled = true;
    const pending = appendAgentMessage("assistant", "正在查询数据库并分析…", "pending");
    try {
      const result = await api("/api/agent/chat", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({message, history: agentHistory}),
      });
      const toolSummary = (result.tool_calls || []).map(item => item.tool).join("、");
      const answer = result.answer || "Agent 未返回文本回答。";
      pending.classList.remove("pending");
      pending.textContent = answer;
      if (toolSummary) {
        const toolElement = document.createElement("span");
        toolElement.className = "agent-tool-summary";
        toolElement.textContent = "已调用：" + toolSummary;
        pending.appendChild(toolElement);
      }
      agentHistory.push(
        {role: "user", content: message},
        {role: "assistant", content: answer},
      );
      agentHistory = agentHistory.slice(-12);
    } catch (error) {
      pending.classList.remove("pending");
      pending.textContent = error.message;
    } finally {
      sendButton.disabled = false;
      input.focus();
    }
  });

  try {
    const capability = await api("/api/agent/capability");
    const statusDot = document.querySelector("#agent-status-dot");
    document.querySelector("#agent-status").textContent = capability.configured
      ? `${capability.model} · 已连接`
      : `尚未配置 AI 密钥`;
    statusDot.classList.add(capability.configured ? "online" : "offline");
  } catch (error) {
    document.querySelector("#agent-status").textContent = error.message;
    document.querySelector("#agent-status-dot").classList.add("offline");
  }
}

initialize();
