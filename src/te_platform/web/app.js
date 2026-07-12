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
    ctx.rect(x - size, y - size, size * 2, size * 2);
  } else if (point.source === "our" || point.source === "This work") {
    ctx.moveTo(x, y - size * 1.25);
    ctx.lineTo(x + size * 1.25, y);
    ctx.lineTo(x, y + size * 1.25);
    ctx.lineTo(x - size * 1.25, y);
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
    const size = point.source === "Exp." ? 4.3 : point.source === "DFT" ? 3.8 : 3.3;
    drawLandscapeMarker(ctx, point, pointX, pointY, size, color);
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
  drawLandscapeMarker(ctx, {source: "Exp."}, legendX, legendY, 4.3, "rgba(68,119,170,.9)");
  ctx.fillText("NTE", legendX + 10, legendY + 4);
  drawLandscapeMarker(ctx, {source: "DFT"}, legendX + 62, legendY, 4, "rgba(253,56,39,.85)");
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
