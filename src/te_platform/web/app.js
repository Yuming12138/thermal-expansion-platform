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
    "</dl><details><summary>查看全部数据字段</summary><pre>" +
    escapeHtml(JSON.stringify(data.properties, null, 2)) + "</pre></details>";
}

function drawLandscape(points) {
  const canvas = document.querySelector("#landscape");
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  const margin = 44;
  ctx.clearRect(0, 0, width, height);
  const valid = points.filter(p => p.G_GPa > 0 && p.E_tilde_GPa > 0);
  const maxG = Math.max(...valid.map(p => p.G_GPa));
  const maxE = Math.max(...valid.map(p => p.E_tilde_GPa));
  ctx.strokeStyle = "#b9c9d7";
  ctx.beginPath();
  ctx.moveTo(margin, 12);
  ctx.lineTo(margin, height - margin);
  ctx.lineTo(width - 12, height - margin);
  ctx.stroke();
  valid.forEach(p => {
    const x = margin + (p.E_tilde_GPa / maxE) * (width - margin - 24);
    const y = height - margin - (p.G_GPa / maxG) * (height - margin - 24);
    ctx.fillStyle = p.G_GPa / p.E_tilde_GPa < 2.84 ? "rgba(36,119,181,.45)" : "rgba(215,111,50,.5)";
    ctx.beginPath();
    ctx.arc(x, y, 2.2, 0, Math.PI * 2);
    ctx.fill();
  });
  ctx.fillStyle = "#516476";
  ctx.font = "13px Segoe UI";
  ctx.fillText("Ẽ (GPa)", width - 86, height - 14);
  ctx.save();
  ctx.translate(15, 82);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText("G (GPa)", 0, 0);
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
}

initialize();
