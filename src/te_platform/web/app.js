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
let agentAttachments = [];
let materialStructureViewer = null;
let materialStructureAxisViewer = null;
let structureFullscreenHandlerInstalled = false;
let catalogElementMode = "contains";
let catalogElementCounts = {};
let catalogSearchSequence = 0;
let comparisonMaterialKeys = [];
const selectedCatalogElements = new Set();
const LANDSCAPE_REFERENCE_MARKER_SIZE = 3.6;
const LANDSCAPE_REFERENCE_PLOT = {width: 670, height: 332};
const MATERIAL_COMPARE_STORAGE_KEY = "tep.material-compare.v1";
const COMPARISON_COLORS = ["#d84a3a", "#2864c7", "#15906f", "#d98624", "#7b57b2", "#5d6a76"];

const PERIODIC_MAIN_ROWS = [
  ["H:1", "He:18"],
  ["Li:1", "Be:2", "B:13", "C:14", "N:15", "O:16", "F:17", "Ne:18"],
  ["Na:1", "Mg:2", "Al:13", "Si:14", "P:15", "S:16", "Cl:17", "Ar:18"],
  ["K:1", "Ca:2", "Sc:3", "Ti:4", "V:5", "Cr:6", "Mn:7", "Fe:8", "Co:9", "Ni:10", "Cu:11", "Zn:12", "Ga:13", "Ge:14", "As:15", "Se:16", "Br:17", "Kr:18"],
  ["Rb:1", "Sr:2", "Y:3", "Zr:4", "Nb:5", "Mo:6", "Tc:7", "Ru:8", "Rh:9", "Pd:10", "Ag:11", "Cd:12", "In:13", "Sn:14", "Sb:15", "Te:16", "I:17", "Xe:18"],
  ["Cs:1", "Ba:2", "La–Lu:3", "Hf:4", "Ta:5", "W:6", "Re:7", "Os:8", "Ir:9", "Pt:10", "Au:11", "Hg:12", "Tl:13", "Pb:14", "Bi:15", "Po:16", "At:17", "Rn:18"],
  ["Fr:1", "Ra:2", "Ac–Lr:3", "Rf:4", "Db:5", "Sg:6", "Bh:7", "Hs:8", "Mt:9", "Ds:10", "Rg:11", "Cn:12", "Nh:13", "Fl:14", "Mc:15", "Lv:16", "Ts:17", "Og:18"],
];
const LANTHANIDES = "La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu".split(" ");
const ACTINIDES = "Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr".split(" ");
const ELEMENT_FAMILIES = {
  alkali: new Set("Li Na K Rb Cs Fr".split(" ")),
  alkaline: new Set("Be Mg Ca Sr Ba Ra".split(" ")),
  transition: new Set("Sc Ti V Cr Mn Fe Co Ni Cu Zn Y Zr Nb Mo Tc Ru Rh Pd Ag Cd Hf Ta W Re Os Ir Pt Au Hg Rf Db Sg Bh Hs Mt Ds Rg Cn".split(" ")),
  "post-transition": new Set("Al Ga In Sn Tl Pb Bi Po Nh Fl Mc Lv".split(" ")),
  metalloid: new Set("B Si Ge As Sb Te".split(" ")),
  nonmetal: new Set("H C N O P S Se".split(" ")),
  halogen: new Set("F Cl Br I At Ts".split(" ")),
  noble: new Set("He Ne Ar Kr Xe Rn Og".split(" ")),
  lanthanide: new Set(LANTHANIDES),
  actinide: new Set(ACTINIDES),
};
const MATERIAL_CONTEXT_STORAGE_KEY = "tep.material-context.v1";
const WORKSPACE_PAGES = {
  database: {path: "/database", title: "材料数据库"},
  predict: {path: "/predict", title: "结构预测"},
  landscape: {path: "/landscape", title: "热膨胀景观"},
  zte: {path: "/zte", title: "ZTE 复合设计"},
  about: {path: "/about", title: "关于软件"},
};

function prepareHiDpiCanvas(canvas) {
  const width = Math.max(1, canvas.clientWidth);
  const height = Math.max(1, canvas.clientHeight);
  const dpr = Math.max(1, Math.min(window.devicePixelRatio || 1, 3));
  const backingWidth = Math.round(width * dpr);
  const backingHeight = Math.round(height * dpr);
  if (canvas.width !== backingWidth || canvas.height !== backingHeight) {
    canvas.width = backingWidth;
    canvas.height = backingHeight;
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return {ctx, width, height};
}

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
  document.querySelector("#stats").innerHTML =
    "<div class='catalog-summary-main'><span>NTE 材料数据库</span><strong>" +
    escapeHtml(counts.materials) + "</strong><span>个活跃材料</span></div>" +
    "<div class='catalog-summary-meta'><span>结构 " + escapeHtml(counts.structures) +
    "</span><span>属性值 " + escapeHtml(counts.property_values) +
    "</span><span>数据版本 " + escapeHtml(dataset.release.version) + "</span></div>";
}

async function loadAbout() {
  const payload = await api("/api/about");
  const software = payload.software;
  const datasets = payload.datasets;
  document.querySelector("#about-name").textContent = software.name_zh;
  document.querySelector("#about-name-en").textContent = software.name_en;
  document.querySelector("#about-version").textContent = "v" + software.version;
  document.querySelector("#about-owner").textContent = software.copyright_owner;
  const repository = document.querySelector("#about-repository");
  repository.href = software.repository;
  repository.textContent = software.repository.replace("https://github.com/", "");
  document.querySelector("#about-nte").textContent =
    datasets.nte_materials + " 条 · " + datasets.nte.version;
  document.querySelector("#about-pte").textContent =
    datasets.pte_materials + " 条 · " + datasets.pte.version;
  document.querySelector("#about-total").textContent = datasets.catalog_materials + " 条";
  document.querySelector("#about-descriptor").textContent =
    payload.descriptor.bonding_modulus + "；正式分类边界 ξc=" +
    Number(payload.descriptor.formal_boundary).toFixed(5) + "。";
  document.querySelector("#about-scope").textContent = payload.scientific_scope;
  document.querySelector("#about-technology").innerHTML = payload.technology
    .map(item => "<span>" + escapeHtml(item) + "</span>")
    .join("");
}

function elementFamily(symbol) {
  return Object.entries(ELEMENT_FAMILIES)
    .find(([, elements]) => elements.has(symbol))?.[0] || "post-transition";
}

function periodicElementButton(symbol, column, row) {
  const count = Number(catalogElementCounts[symbol] || 0);
  const button = document.createElement("button");
  button.type = "button";
  button.className = "periodic-element element-family-" + elementFamily(symbol);
  button.style.gridColumn = String(column);
  button.style.gridRow = String(row);
  button.dataset.element = symbol;
  button.textContent = symbol;
  button.title = symbol + " · " + count + " 个材料";
  button.setAttribute("aria-label", symbol + "，数据库中 " + count + " 个材料");
  button.setAttribute("aria-pressed", String(selectedCatalogElements.has(symbol)));
  if (selectedCatalogElements.has(symbol)) button.classList.add("selected");
  if (!count) {
    button.classList.add("unavailable");
    button.disabled = true;
  }
  button.addEventListener("click", () => {
    if (selectedCatalogElements.has(symbol)) selectedCatalogElements.delete(symbol);
    else selectedCatalogElements.add(symbol);
    renderPeriodicTable();
    updateElementFilterSummary();
    searchMaterials();
  });
  return button;
}

function renderPeriodicTable() {
  const container = document.querySelector("#periodic-table");
  container.replaceChildren();
  PERIODIC_MAIN_ROWS.forEach((entries, rowIndex) => {
    entries.forEach(entry => {
      const [symbol, column] = entry.split(":");
      if (symbol.includes("–")) {
        const placeholder = document.createElement("span");
        placeholder.className = "periodic-placeholder";
        placeholder.style.gridColumn = column;
        placeholder.style.gridRow = String(rowIndex + 1);
        placeholder.textContent = symbol;
        container.append(placeholder);
      } else {
        container.append(periodicElementButton(symbol, Number(column), rowIndex + 1));
      }
    });
  });
  const lanthanideLabel = document.createElement("span");
  lanthanideLabel.className = "periodic-series-label";
  lanthanideLabel.style.gridColumn = "1 / 4";
  lanthanideLabel.style.gridRow = "8";
  lanthanideLabel.textContent = "镧系";
  container.append(lanthanideLabel);
  LANTHANIDES.forEach((symbol, index) => container.append(periodicElementButton(symbol, index + 4, 8)));
  const actinideLabel = document.createElement("span");
  actinideLabel.className = "periodic-series-label";
  actinideLabel.style.gridColumn = "1 / 4";
  actinideLabel.style.gridRow = "9";
  actinideLabel.textContent = "锕系";
  container.append(actinideLabel);
  ACTINIDES.forEach((symbol, index) => container.append(periodicElementButton(symbol, index + 4, 9)));
}

function updateElementFilterSummary() {
  document.querySelectorAll("[data-element-mode]").forEach(button => {
    button.classList.toggle("active", button.dataset.elementMode === catalogElementMode);
  });
  const selected = [...selectedCatalogElements];
  const modeText = catalogElementMode === "exact" ? "仅含" : "包含";
  document.querySelector("#element-selection").textContent = selected.length
    ? modeText + "：" + selected.join(" · ")
    : "尚未选择元素";
  document.querySelector("#element-clear").disabled = !selected.length;
}

async function loadPeriodicElementCounts() {
  const result = await api("/api/materials/elements");
  catalogElementCounts = result.elements || {};
  renderPeriodicTable();
  updateElementFilterSummary();
}

function setupElementFilter() {
  document.querySelectorAll("[data-element-mode]").forEach(button => {
    button.addEventListener("click", () => {
      catalogElementMode = button.dataset.elementMode;
      updateElementFilterSummary();
      if (selectedCatalogElements.size) searchMaterials();
    });
  });
  document.querySelector("#element-clear").addEventListener("click", () => {
    selectedCatalogElements.clear();
    renderPeriodicTable();
    updateElementFilterSummary();
    searchMaterials();
  });
  updateElementFilterSummary();
}

function workspacePageFromPath(pathname = window.location.pathname) {
  return Object.entries(WORKSPACE_PAGES)
    .find(([, page]) => page.path === pathname)?.[0] || "database";
}

function validLandscapeContext(point) {
  return point && typeof point.material_key === "string" &&
    Number.isFinite(Number(point.x_gpa)) && Number(point.x_gpa) > 0 &&
    Number.isFinite(Number(point.g_gpa)) && Number(point.g_gpa) > 0;
}

function landscapeSelectionText(point) {
  if (!validLandscapeContext(point)) return "尚未选择材料。";
  const prefix = point.context_origin === "predict" ? "当前预测：" : "当前材料：";
  return prefix + point.material_key + " · Ẽ=" + Number(point.x_gpa).toFixed(3) +
    " GPa · G=" + Number(point.g_gpa).toFixed(3) + " GPa";
}

function restoreLandscapeContext() {
  try {
    const stored = JSON.parse(window.sessionStorage.getItem(MATERIAL_CONTEXT_STORAGE_KEY));
    if (validLandscapeContext(stored)) {
      selectedLandscapePoint = stored;
      document.querySelector("#landscape-selection").textContent = landscapeSelectionText(stored);
    }
  } catch (error) {
    console.warn("无法恢复当前材料上下文", error);
  }
}

function persistLandscapeContext() {
  try {
    if (selectedLandscapePoint) {
      window.sessionStorage.setItem(MATERIAL_CONTEXT_STORAGE_KEY, JSON.stringify(selectedLandscapePoint));
    } else {
      window.sessionStorage.removeItem(MATERIAL_CONTEXT_STORAGE_KEY);
    }
  } catch (error) {
    console.warn("无法保存当前材料上下文", error);
  }
}

function workspaceUrl(pageName) {
  const page = WORKSPACE_PAGES[pageName] || WORKSPACE_PAGES.database;
  if (pageName === "landscape" && selectedLandscapePoint?.context_origin === "database" &&
      selectedLandscapePoint.database_key) {
    return page.path + "?material=" + encodeURIComponent(selectedLandscapePoint.database_key);
  }
  return page.path;
}

function updateMaterialContextUi(activePage = workspacePageFromPath()) {
  const container = document.querySelector("#material-context");
  const landscapeLink = document.querySelector("[data-page-link='landscape']");
  landscapeLink?.classList.toggle("has-context", Boolean(selectedLandscapePoint));
  if (!selectedLandscapePoint) {
    container.hidden = true;
    return;
  }
  const point = selectedLandscapePoint;
  container.hidden = false;
  document.querySelector("#material-context-source").textContent = point.source || "当前材料";
  document.querySelector("#material-context-name").textContent = point.material_key;
  document.querySelector("#material-context-metrics").textContent =
    "G=" + Number(point.g_gpa).toFixed(3) + " GPa · Ẽ=" + Number(point.x_gpa).toFixed(3) + " GPa";
  const classification = document.querySelector("#material-context-classification");
  classification.textContent = point.classification || "未判定";
  classification.className = "material-context-classification " +
    (point.classification === "NTE" ? "nte" : point.classification === "PTE" ? "pte" : "");
  const origin = document.querySelector("#material-context-origin");
  origin.textContent = point.context_origin === "predict" ? "返回预测工作台" : "返回材料详情";
  origin.hidden = !point.context_origin;
  const landscape = document.querySelector("#material-context-landscape");
  landscape.disabled = activePage === "landscape";
  landscape.textContent = activePage === "landscape" ? "已在景观中定位" : "在景观中定位";
}

function setLandscapeContext(point, selectionText) {
  selectedLandscapePoint = validLandscapeContext(point) ? point : null;
  persistLandscapeContext();
  updateMaterialContextUi();
  document.querySelector("#landscape-selection").textContent =
    selectionText || landscapeSelectionText(selectedLandscapePoint);
  drawLandscape();
}

function clearLandscapeContext({replaceUrl = true} = {}) {
  selectedLandscapePoint = null;
  persistLandscapeContext();
  updateMaterialContextUi();
  document.querySelector("#landscape-selection").textContent = "尚未选择材料。";
  drawLandscape();
  if (replaceUrl && window.location.pathname === WORKSPACE_PAGES.landscape.path && window.location.search) {
    window.history.replaceState({page: "landscape"}, "", WORKSPACE_PAGES.landscape.path);
  }
}

function focusLandscapeContext() {
  if (!selectedLandscapePoint) return;
  const wrap = document.querySelector(".landscape-wrap");
  wrap.classList.remove("context-focus");
  window.requestAnimationFrame(() => wrap.classList.add("context-focus"));
  window.setTimeout(() => wrap.classList.remove("context-focus"), 1250);
}

function showWorkspacePage(pageName, {updateHistory = false} = {}) {
  const selectedPage = WORKSPACE_PAGES[pageName] ? pageName : "database";
  const page = WORKSPACE_PAGES[selectedPage];
  document.querySelectorAll("[data-page]").forEach(section => {
    section.hidden = section.dataset.page !== selectedPage;
  });
  document.querySelectorAll("[data-page-link]").forEach(link => {
    if (link.dataset.pageLink === selectedPage) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  document.title = page.title + " · 热膨胀材料智能计算与设计平台";
  const targetUrl = workspaceUrl(selectedPage);
  if (updateHistory && window.location.pathname + window.location.search !== targetUrl) {
    window.history.pushState({page: selectedPage}, "", targetUrl);
  }
  updateMaterialContextUi(selectedPage);
  window.requestAnimationFrame(() => {
    const activePage = document.querySelector(`[data-page='${selectedPage}']`);
    activePage?.querySelectorAll("canvas").forEach(canvas => canvas.teRedraw?.());
    materialStructureViewer?.resize?.();
    materialStructureViewer?.render?.();
    materialStructureAxisViewer?.resize?.();
    materialStructureAxisViewer?.render?.();
    if (selectedPage === "landscape") focusLandscapeContext();
  });
}

function navigateToWorkspace(pageName) {
  showWorkspacePage(pageName, {updateHistory: true});
  const navigation = document.querySelector(".workspace-nav");
  window.scrollTo({top: navigation.offsetTop, behavior: "auto"});
}

async function restoreLandscapeContextFromLocation() {
  if (window.location.pathname !== WORKSPACE_PAGES.landscape.path) return;
  const materialKey = new URLSearchParams(window.location.search).get("material");
  if (!materialKey || selectedLandscapePoint?.database_key === materialKey) return;
  const data = await api("/api/materials/" + encodeURIComponent(materialKey));
  selectLandscapeMaterial(data);
}

function setupMaterialContext() {
  document.querySelector("#material-context-landscape").addEventListener("click", () =>
    navigateToWorkspace("landscape"));
  document.querySelector("#material-context-origin").addEventListener("click", async () => {
    const point = selectedLandscapePoint;
    if (!point) return;
    const origin = point.context_origin === "predict" ? "predict" : "database";
    navigateToWorkspace(origin);
    if (origin === "database" && point.database_key) {
      try {
        await loadDetail(point.database_key);
        document.querySelector(".detail-panel").scrollIntoView({behavior: "smooth", block: "start"});
      } catch (error) {
        document.querySelector("#material-detail").textContent = error.message;
      }
    }
  });
  document.querySelector("#material-context-clear").addEventListener("click", () => clearLandscapeContext());
  document.addEventListener("click", event => {
    if (event.target.closest("[data-context-action='landscape']")) navigateToWorkspace("landscape");
  });
}

function setupWorkspaceNavigation() {
  document.querySelectorAll("[data-page-link]").forEach(link => {
    link.addEventListener("click", event => {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      navigateToWorkspace(link.dataset.pageLink);
    });
  });
  window.addEventListener("popstate", async () => {
    try {
      await restoreLandscapeContextFromLocation();
    } catch (error) {
      console.warn("无法恢复景观材料", error);
    }
    showWorkspacePage(workspacePageFromPath());
  });
  showWorkspacePage(workspacePageFromPath());
}

function restoreComparisonMaterials() {
  try {
    const stored = JSON.parse(window.localStorage.getItem(MATERIAL_COMPARE_STORAGE_KEY));
    comparisonMaterialKeys = Array.isArray(stored)
      ? [...new Set(stored.filter(item => typeof item === "string" && item.trim()))].slice(0, 4)
      : [];
  } catch (error) {
    console.warn("无法恢复材料收藏", error);
    comparisonMaterialKeys = [];
  }
}

function persistComparisonMaterials() {
  try {
    window.localStorage.setItem(MATERIAL_COMPARE_STORAGE_KEY, JSON.stringify(comparisonMaterialKeys));
  } catch (error) {
    console.warn("无法保存材料收藏", error);
  }
}

function comparisonSelected(materialKey) {
  return comparisonMaterialKeys.includes(materialKey);
}

function updateComparisonButtons() {
  document.querySelectorAll("button[data-compare-key]").forEach(button => {
    const materialKey = decodeURIComponent(button.dataset.compareKey);
    const selected = comparisonSelected(materialKey);
    button.classList.toggle("selected", selected);
    button.textContent = selected ? "已收藏" : "收藏";
    button.setAttribute("aria-pressed", String(selected));
  });
}

function renderComparisonSelection() {
  const selection = document.querySelector("#material-compare-selection");
  const runButton = document.querySelector("#material-compare-run");
  const clearButton = document.querySelector("#material-compare-clear");
  runButton.disabled = comparisonMaterialKeys.length < 2;
  clearButton.disabled = comparisonMaterialKeys.length === 0;
  if (!comparisonMaterialKeys.length) {
    selection.className = "compare-selection muted";
    selection.textContent = "尚未收藏材料。";
  } else {
    selection.className = "compare-selection";
    selection.innerHTML = comparisonMaterialKeys.map(materialKey =>
      "<span class='compare-chip'><span>" + escapeHtml(materialKey) + "</span>" +
      "<button type='button' data-compare-remove='" +
      escapeHtml(encodeURIComponent(materialKey)) + "' aria-label='移除 " +
      escapeHtml(materialKey) + "'>×</button></span>"
    ).join("");
    selection.querySelectorAll("button[data-compare-remove]").forEach(button => {
      button.addEventListener("click", () => toggleComparisonMaterial(
        decodeURIComponent(button.dataset.compareRemove),
      ));
    });
  }
  updateComparisonButtons();
  const result = document.querySelector("#material-compare-result");
  result.className = "compare-result placeholder";
  result.textContent = comparisonMaterialKeys.length >= 2
    ? "收藏列表已更新，请点击“生成对比”读取属性和真实QHA曲线。"
    : "至少收藏两个材料后即可生成对比。";
}

function toggleComparisonMaterial(materialKey) {
  if (comparisonSelected(materialKey)) {
    comparisonMaterialKeys = comparisonMaterialKeys.filter(item => item !== materialKey);
  } else if (comparisonMaterialKeys.length >= 4) {
    const result = document.querySelector("#material-compare-result");
    result.className = "compare-result";
    result.textContent = "一次最多收藏并对比 4 个材料，请先移除一个材料。";
    return;
  } else {
    comparisonMaterialKeys.push(materialKey);
  }
  persistComparisonMaterials();
  renderComparisonSelection();
}

function comparisonFilterBounds() {
  const selected = document.querySelector("#material-cte-filter").value;
  return {
    strong: {cte_max_ppm: "-20"},
    moderate: {cte_min_ppm: "-20", cte_max_ppm: "-5"},
    "near-zero": {cte_min_ppm: "-5", cte_max_ppm: "5"},
    positive: {cte_min_ppm: "5"},
  }[selected] || {};
}

function renderMaterials(items) {
  const container = document.querySelector("#material-results");
  const filterDescription = selectedCatalogElements.size
    ? " · " + (catalogElementMode === "exact" ? "仅含 " : "包含 ") + [...selectedCatalogElements].join("/")
    : "";
  document.querySelector("#material-view-summary").textContent =
    "显示 " + items.length + " 条" + filterDescription;
  if (!items.length) {
    container.innerHTML = "<p class='muted'>没有匹配材料。</p>";
    return;
  }
  const rows = items.map(item => {
    const encodedKey = escapeHtml(encodeURIComponent(item.material_key));
    const selectedClass = comparisonSelected(item.material_key) ? " selected" : "";
    const selectedText = comparisonSelected(item.material_key) ? "已收藏" : "收藏";
    return "<tr><td>" + escapeHtml(item.material_key) + "</td><td>" + numeric(item.G_GPa) +
      "</td><td>" + numeric(item.E_tilde_GPa) + "</td><td>" + numeric(item.xi) +
      "</td><td>" + numeric(item.CTE_ppm) + "</td><td><div class='material-row-actions'>" +
      "<button class='compare-toggle" + selectedClass + "' data-compare-key='" + encodedKey +
      "' aria-pressed='" + String(comparisonSelected(item.material_key)) + "'>" + selectedText +
      "</button><button data-key='" + encodedKey + "'>详情</button></div></td></tr>";
  }).join("");
  container.innerHTML = "<table><thead><tr><th>材料</th><th>G</th><th>Ẽ</th><th>ξ</th><th>CTE</th><th></th></tr></thead><tbody>" + rows + "</tbody></table>";
  container.querySelectorAll("button[data-key]").forEach(button => {
    button.addEventListener("click", () => loadDetail(decodeURIComponent(button.dataset.key)));
  });
  container.querySelectorAll("button[data-compare-key]").forEach(button => {
    button.addEventListener("click", () => toggleComparisonMaterial(
      decodeURIComponent(button.dataset.compareKey),
    ));
  });
}

async function searchMaterials() {
  const query = document.querySelector("#search-input").value;
  const requestId = ++catalogSearchSequence;
  document.querySelector("#material-view-summary").textContent = "正在检索…";
  const params = new URLSearchParams({
    limit: document.querySelector("#material-limit").value,
    query,
    elements: [...selectedCatalogElements].join(","),
    element_mode: catalogElementMode,
    sort_by: document.querySelector("#material-sort-by").value,
    sort_order: document.querySelector("#material-sort-order").value,
    ...comparisonFilterBounds(),
  });
  try {
    const items = await api("/api/materials?" + params.toString());
    if (requestId === catalogSearchSequence) renderMaterials(items);
  } catch (error) {
    if (requestId !== catalogSearchSequence) return;
    document.querySelector("#material-view-summary").textContent = "检索失败";
    document.querySelector("#material-results").innerHTML =
      "<p class='structure-error'>" + escapeHtml(error.message) + "</p>";
  }
}

function displaySourceName(value) {
  const text = String(value || "未记录");
  const parts = text.split(/[\\/]/);
  return parts[parts.length - 1] || text;
}

function renderMaterialProvenance(data) {
  const release = data.dataset_release || {};
  const notes = data.method_notes || {};
  const curve = data.precision_thermal_expansion;
  const checksum = release.source_sha256 ? String(release.source_sha256).slice(0, 16) + "…" : "未记录";
  const curveSource = curve
    ? escapeHtml(displaySourceName(curve.source_path)) + " · " +
      escapeHtml(curve.model_name || "模型未记录")
    : "暂无已关联的精确QHA曲线";
  return "<section class='provenance-card'><h3>数据来源与方法</h3><dl>" +
    "<dt>数据版本</dt><dd>" + escapeHtml(release.title || release.slug || "未记录") +
    " · v" + escapeHtml(release.version || "—") + "</dd>" +
    "<dt>源数据文件</dt><dd>" + escapeHtml(displaySourceName(release.source_file_name)) +
    " · SHA256 " + escapeHtml(checksum) + "</dd>" +
    "<dt>剪切模量 G</dt><dd>" + escapeHtml(notes.G_GPa || "目录字段") + "</dd>" +
    "<dt>键合模量 Ẽ</dt><dd>" + escapeHtml(notes.E_tilde_GPa || "按论文定义计算") + "</dd>" +
    "<dt>目录 CTE</dt><dd>" + escapeHtml(notes.CTE_ppm || "目录筛选字段") + "</dd>" +
    "<dt>QHA 曲线</dt><dd>" + curveSource + "</dd></dl></section>";
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
  const encodedKey = escapeHtml(encodeURIComponent(data.material.material_key));
  document.querySelector("#material-detail").innerHTML =
    "<div class='compare-summary'><p><strong>" + escapeHtml(data.material.material_key) +
    "</strong> · " + escapeHtml(data.material.external_id || "无外部ID") + "</p>" +
    "<button class='compare-toggle' data-compare-key='" + encodedKey + "' type='button'>收藏</button></div>" +
    landscapeJumpAction("已设为当前研究材料，可在论文景观中查看相对位置。") +
    "<p class='muted'>结构：" + escapeHtml(structures) + "</p><dl class='property-grid'>" + metrics +
    "</dl>" + renderMaterialProvenance(data) +
    "<div class='material-visual-grid'>" + renderStructureViewer(data.structures) +
    renderPrecisionThermalExpansion(data.precision_thermal_expansion) + "</div>" +
    "<details><summary>查看全部数据字段</summary><pre>" +
    escapeHtml(JSON.stringify(data.properties, null, 2)) + "</pre></details>";
  const detailCompareButton = document.querySelector("#material-detail button[data-compare-key]");
  detailCompareButton.addEventListener("click", () => toggleComparisonMaterial(data.material.material_key));
  updateComparisonButtons();
  drawMaterialStructure(data.material, data.structures?.[0], data.structure_view);
  drawPrecisionThermalExpansion(data.precision_thermal_expansion);
  selectLandscapeMaterial(data);
}

function comparisonMetric(value, unit = "") {
  return Number.isFinite(Number(value)) ? numeric(value) + (unit ? " " + unit : "") : "—";
}

function renderMaterialComparison(payload) {
  const result = document.querySelector("#material-compare-result");
  const temperature = Number(payload.temperature_k);
  const columns = payload.materials.map(item =>
    "<th>" + escapeHtml(item.material.material_key) + "</th>"
  ).join("");
  const metricRows = [
    ["G", "G_GPa", "GPa"],
    ["Ẽ", "E_tilde_GPa", "GPa"],
    ["ξ = G/Ẽ", "xi", ""],
    ["目录 CTE", "CTE_ppm", "ppm/K"],
    [temperature.toFixed(0) + " K 曲线 α", "alpha_at_temperature_ppm_per_k", "ppm/K"],
    ["体积模量 K", "K_GPa", "GPa"],
    ["内聚能", "E_coh_eV_per_atom", "eV/atom"],
    ["平均配位数", "avg_cn", ""],
  ].map(([label, key, unit]) =>
    "<tr><th>" + escapeHtml(label) + "</th>" + payload.materials.map(item =>
      "<td>" + comparisonMetric(item.metrics[key], unit) + "</td>"
    ).join("") + "</tr>"
  ).join("");
  const detailButtons = payload.materials.map(item =>
    "<td><button type='button' data-comparison-detail='" +
    escapeHtml(encodeURIComponent(item.material.material_key)) + "'>查看详情</button></td>"
  ).join("");
  const curveCount = payload.materials.filter(item => item.curve?.points?.length >= 2).length;
  result.className = "compare-result";
  result.innerHTML =
    "<div class='compare-summary'><strong>已比较 " + payload.material_count + " 个材料</strong>" +
    "<span>" + escapeHtml(payload.method_note) + "</span></div>" +
    "<div class='table-wrap'><table class='comparison-table'><thead><tr><th>指标</th>" + columns +
    "</tr></thead><tbody>" + metricRows + "<tr><th>材料详情</th>" + detailButtons +
    "</tr></tbody></table></div>" +
    (curveCount
      ? "<canvas id='material-comparison-chart' class='comparison-chart' width='1100' height='480' " +
        "aria-label='收藏材料的QHA热膨胀曲线对比'></canvas>"
      : "<p class='muted'>所选材料暂无可共同展示的已关联QHA曲线。</p>");
  result.querySelectorAll("button[data-comparison-detail]").forEach(button => {
    button.addEventListener("click", async () => {
      await loadDetail(decodeURIComponent(button.dataset.comparisonDetail));
      document.querySelector(".detail-panel").scrollIntoView({behavior: "smooth", block: "start"});
    });
  });
  if (curveCount) drawMaterialComparisonCurves(payload);
}

function drawMaterialComparisonCurves(payload) {
  const canvas = document.querySelector("#material-comparison-chart");
  if (!canvas) return;
  const series = payload.materials
    .map((item, index) => ({
      key: item.material.material_key,
      color: COMPARISON_COLORS[index % COMPARISON_COLORS.length],
      points: (item.curve?.points || [])
        .map(point => ({x: Number(point.temperature_k), y: Number(point.alpha_ppm_per_k)}))
        .filter(point => Number.isFinite(point.x) && Number.isFinite(point.y)),
    }))
    .filter(item => item.points.length >= 2);
  if (!series.length) return;
  const {ctx, width, height} = prepareHiDpiCanvas(canvas);
  const margin = {left: 66, right: 20, top: 46, bottom: 50};
  const plotWidth = Math.max(1, width - margin.left - margin.right);
  const plotHeight = Math.max(1, height - margin.top - margin.bottom);
  const allPoints = series.flatMap(item => item.points);
  let xMin = Math.min(...allPoints.map(point => point.x));
  let xMax = Math.max(...allPoints.map(point => point.x));
  let yMin = Math.min(0, ...allPoints.map(point => point.y));
  let yMax = Math.max(0, ...allPoints.map(point => point.y));
  if (xMax === xMin) xMax = xMin + 1;
  if (yMax === yMin) yMax = yMin + 1;
  const yPadding = Math.max(1, (yMax - yMin) * .08);
  yMin -= yPadding;
  yMax += yPadding;
  const xScale = value => margin.left + (value - xMin) / (xMax - xMin) * plotWidth;
  const yScale = value => margin.top + plotHeight - (value - yMin) / (yMax - yMin) * plotHeight;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, width, height);
  ctx.font = "12px Segoe UI, Microsoft YaHei, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  for (let index = 0; index <= 5; index += 1) {
    const xValue = xMin + (xMax - xMin) * index / 5;
    const yValue = yMin + (yMax - yMin) * index / 5;
    const x = xScale(xValue);
    const y = yScale(yValue);
    ctx.strokeStyle = "#e7edf2";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, margin.top);
    ctx.lineTo(x, margin.top + plotHeight);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(margin.left, y);
    ctx.lineTo(margin.left + plotWidth, y);
    ctx.stroke();
    ctx.fillStyle = "#657889";
    ctx.fillText(xValue.toFixed(0), x, height - 28);
    ctx.textAlign = "right";
    ctx.fillText(yValue.toFixed(1), margin.left - 9, y);
    ctx.textAlign = "center";
  }
  if (yMin <= 0 && yMax >= 0) {
    ctx.strokeStyle = "#9aa8b4";
    ctx.setLineDash([5, 4]);
    ctx.beginPath();
    ctx.moveTo(margin.left, yScale(0));
    ctx.lineTo(margin.left + plotWidth, yScale(0));
    ctx.stroke();
    ctx.setLineDash([]);
  }
  series.forEach(item => {
    ctx.strokeStyle = item.color;
    ctx.lineWidth = 2.2;
    ctx.beginPath();
    item.points.forEach((point, index) => {
      if (index === 0) ctx.moveTo(xScale(point.x), yScale(point.y));
      else ctx.lineTo(xScale(point.x), yScale(point.y));
    });
    ctx.stroke();
  });
  ctx.fillStyle = "#445b6d";
  ctx.fillText("温度 T (K)", margin.left + plotWidth / 2, height - 10);
  ctx.save();
  ctx.translate(16, margin.top + plotHeight / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText("体热膨胀系数 α (ppm/K)", 0, 0);
  ctx.restore();
  let legendX = margin.left;
  series.forEach(item => {
    const label = item.key.length > 24 ? item.key.slice(0, 22) + "…" : item.key;
    ctx.fillStyle = item.color;
    ctx.fillRect(legendX, 18, 14, 3);
    ctx.textAlign = "left";
    ctx.fillStyle = "#40586a";
    ctx.fillText(label, legendX + 19, 20);
    legendX += Math.min(230, 38 + ctx.measureText(label).width);
  });
  ctx.textAlign = "center";
  canvas.teRedraw = () => drawMaterialComparisonCurves(payload);
}

async function loadMaterialComparison() {
  if (comparisonMaterialKeys.length < 2) return;
  const result = document.querySelector("#material-compare-result");
  result.className = "compare-result placeholder";
  result.textContent = "正在读取材料属性和真实QHA曲线…";
  const temperature = Number(document.querySelector("#material-compare-temperature").value);
  const params = new URLSearchParams({
    material_keys: comparisonMaterialKeys.join("|"),
    temperature_k: Number.isFinite(temperature) && temperature >= 0 ? String(temperature) : "300",
  });
  try {
    renderMaterialComparison(await api("/api/materials/compare?" + params.toString()));
  } catch (error) {
    result.className = "compare-result";
    result.textContent = error.message;
  }
}

function renderStructureViewer(structures) {
  const structure = structures?.find(item => item.content) || null;
  if (!structure) {
    return "<h3>三维晶体结构</h3><p class='muted'>暂无可用于三维显示的结构文件。</p>";
  }
  return "<section class='structure-panel' id='structure-panel'>" +
    "<div class='structure-heading'><div><h3>三维晶体结构</h3>" +
    "<p class='curve-note'>左键拖拽旋转 · 滚轮缩放 · 中键或 Ctrl+拖拽平移</p></div>" +
    "<span id='material-structure-summary' class='structure-summary-badge'>正在加载…</span></div>" +
    "<div class='structure-stage'>" +
    "<div id='structure-viewer' class='structure-viewer' role='img' aria-label='可旋转缩放的三维晶体结构'></div>" +
    "<div class='structure-viewer-tools' role='toolbar' aria-label='三维结构工具'>" +
    structureToolButton("structure-fullscreen", "全屏", "fullscreen") +
    structureToolButton("structure-settings-button", "显示设置", "settings") +
    structureToolButton("structure-reset", "重置视角", "reset") +
    structureToolButton("structure-snapshot", "保存图片", "camera") +
    "</div>" +
    "<div id='structure-settings' class='structure-settings' hidden>" +
    "<strong>显示设置</strong>" +
    "<label>原子样式<select id='structure-style'><option value='ball-stick'>球棍</option>" +
    "<option value='spacefill'>空间填充</option><option value='stick'>键线</option></select></label>" +
    "<label>显示范围<select id='structure-supercell'><option value='periodic'>周期邻居（推荐）</option>" +
    "<option value='1'>1×1×1 原胞</option>" +
    "<option value='2'>2×2×2</option><option value='3'>3×3×3</option></select></label>" +
    "<label class='structure-checkbox'><input id='structure-unit-cell' type='checkbox' checked>显示晶胞边框</label>" +
    "</div>" +
    "<div id='structure-axis-viewer' class='structure-axis-viewer' role='img' " +
    "aria-label='随晶体旋转的三维坐标轴'></div>" +
    "<div id='structure-element-legend' class='structure-element-legend' aria-label='元素图例'></div>" +
    "</div>" +
    "<p id='structure-atom-info' class='structure-atom-info'>点击原子可查看元素和笛卡尔坐标。</p>" +
    "</section>";
}

function structureToolButton(id, label, icon) {
  const paths = {
    fullscreen: "<path d='M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5'/>",
    settings: "<path d='M4 7h10M18 7h2M4 17h2M10 17h10M14 4v6M8 14v6'/>",
    reset: "<path d='M5 8V3m0 0h5M5 3l4 4a7 7 0 1 1-2 9'/>",
    camera: "<path d='M4 8h3l2-3h6l2 3h3v11H4z'/><circle cx='12' cy='13' r='3'/>",
  };
  return "<button id='" + id + "' type='button' title='" + label + "' aria-label='" + label + "'>" +
    "<svg viewBox='0 0 24 24' aria-hidden='true'>" + paths[icon] + "</svg></button>";
}

const structureElementColors = {
  H: "#f1f1f1", He: "#d9ffff", Li: "#cc80ff", Be: "#c2ff00", B: "#ffb5b5",
  C: "#666a73", N: "#5475d1", O: "#e84a3c", F: "#9fb4dc", Ne: "#b3e3f5",
  Na: "#ab5cf2", Mg: "#8aff00", Al: "#b8a1a1", Si: "#d6ad8b", P: "#e58a37",
  S: "#e1c229", Cl: "#58a65c", Ar: "#80d1e3", K: "#8f40d4", Ca: "#3dff00",
  Sc: "#bfc4c7", Ti: "#9ba3a8", V: "#8f99a6", Cr: "#7f8aa6", Mn: "#9c7ac7",
  Fe: "#c97845", Co: "#d989a4", Ni: "#65a56f", Cu: "#c9864e", Zn: "#8299b5",
  Ga: "#b48270", Ge: "#7094a1", As: "#bd80e3", Se: "#d89b34", Br: "#a85845",
  Kr: "#5cb8d1", Rb: "#7830b5", Sr: "#38e600", Y: "#a9c7c7", Zr: "#91a8a8",
  Nb: "#779999", Mo: "#659a9a", Tc: "#4e8f8f", Ru: "#3b7d8f", Rh: "#397b7f",
  Pd: "#8c8c9b", Ag: "#b9bec8", Cd: "#d3c36b", In: "#a67573", Sn: "#668080",
  Sb: "#9e63b5", Te: "#c88a2e", I: "#864e9e", Xe: "#429eb0", Cs: "#57178f",
  Ba: "#24c92e", La: "#70d4ff", Ce: "#70d4ff", W: "#426696", Pt: "#aaa6a0",
  Au: "#e0ae25", Hg: "#b8b8cf", Pb: "#575961", Bi: "#9e4fb5",
};

const structureCovalentRadii = {
  H: .31, He: .28, Li: 1.28, Be: .96, B: .84, C: .76, N: .71, O: .66, F: .57, Ne: .58,
  Na: 1.66, Mg: 1.41, Al: 1.21, Si: 1.11, P: 1.07, S: 1.05, Cl: 1.02, Ar: 1.06,
  K: 2.03, Ca: 1.76, Sc: 1.70, Ti: 1.60, V: 1.53, Cr: 1.39, Mn: 1.39, Fe: 1.32,
  Co: 1.26, Ni: 1.24, Cu: 1.32, Zn: 1.22, Ga: 1.22, Ge: 1.20, As: 1.19, Se: 1.20,
  Br: 1.20, Kr: 1.16, Rb: 2.20, Sr: 1.95, Y: 1.90, Zr: 1.75, Nb: 1.64, Mo: 1.54,
  Tc: 1.47, Ru: 1.46, Rh: 1.42, Pd: 1.39, Ag: 1.45, Cd: 1.44, In: 1.42, Sn: 1.39,
  Sb: 1.39, Te: 1.38, I: 1.39, Xe: 1.40, Cs: 2.44, Ba: 2.15, La: 2.07, Ce: 2.04,
  Pr: 2.03, Nd: 2.01, Sm: 1.98, Eu: 1.98, Gd: 1.96, Tb: 1.94, Dy: 1.92, Ho: 1.92,
  Er: 1.89, Tm: 1.90, Yb: 1.87, Lu: 1.87, Hf: 1.75, Ta: 1.70, W: 1.62, Re: 1.51,
  Os: 1.44, Ir: 1.41, Pt: 1.36, Au: 1.36, Hg: 1.32, Tl: 1.45, Pb: 1.46, Bi: 1.48,
};

function parsePoscar(content) {
  const lines = String(content).split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  if (lines.length < 8) throw new Error("POSCAR 内容不完整");
  const rawScale = Number(lines[1]);
  const rawLattice = lines.slice(2, 5).map(line => line.split(/\s+/).slice(0, 3).map(Number));
  if (!Number.isFinite(rawScale) || rawLattice.some(row => row.length !== 3 || row.some(value => !Number.isFinite(value)))) {
    throw new Error("POSCAR 晶格参数无效");
  }
  const rawVolume = Math.abs(matrixDeterminant3(rawLattice));
  const scale = rawScale < 0 ? Math.cbrt(Math.abs(rawScale) / rawVolume) : rawScale;
  const lattice = rawLattice.map(row => row.map(value => value * scale));
  let cursor = 5;
  const firstTokens = lines[cursor].split(/\s+/);
  let elements;
  let counts;
  if (firstTokens.every(token => /^\d+$/.test(token))) {
    counts = firstTokens.map(Number);
    const titleElements = lines[0].match(/[A-Z][a-z]?/g) || [];
    elements = titleElements.length === counts.length ? titleElements : counts.map((_, index) => "X" + (index + 1));
    cursor += 1;
  } else {
    elements = firstTokens;
    counts = lines[cursor + 1].split(/\s+/).map(Number);
    cursor += 2;
  }
  if (elements.length !== counts.length || counts.some(value => !Number.isInteger(value) || value < 0)) {
    throw new Error("POSCAR 元素或原子计数无效");
  }
  if (/^s/i.test(lines[cursor])) cursor += 1;
  const direct = /^d/i.test(lines[cursor]);
  const cartesian = /^[ck]/i.test(lines[cursor]);
  if (!direct && !cartesian) throw new Error("POSCAR 坐标类型无法识别");
  cursor += 1;
  const atomTotal = counts.reduce((sum, value) => sum + value, 0);
  if (lines.length < cursor + atomTotal) throw new Error("POSCAR 原子坐标数量不足");
  const inverseLattice = matrixInverse3(lattice);
  const expandedElements = elements.flatMap((element, index) => Array(counts[index]).fill(element));
  const atoms = expandedElements.map((element, index) => {
    const values = lines[cursor + index].split(/\s+/).slice(0, 3).map(Number);
    if (values.some(value => !Number.isFinite(value))) throw new Error("POSCAR 原子坐标无效");
    const inputCart = direct ? fractionalToCartesian(values, lattice) : values.map(value => value * scale);
    const inputFractional = direct ? values : vectorMatrixMultiply(inputCart, inverseLattice);
    const fractional = inputFractional.map(value => ((value % 1) + 1) % 1);
    return {element, fractional, cart: fractionalToCartesian(fractional, lattice)};
  });
  return {atoms, lattice};
}

function matrixDeterminant3(matrix) {
  const [[a, b, c], [d, e, f], [g, h, i]] = matrix;
  return a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g);
}

function matrixInverse3(matrix) {
  const [[a, b, c], [d, e, f], [g, h, i]] = matrix;
  const determinant = matrixDeterminant3(matrix);
  if (Math.abs(determinant) < 1e-12) throw new Error("POSCAR 晶格矩阵不可逆");
  return [
    [(e * i - f * h) / determinant, (c * h - b * i) / determinant, (b * f - c * e) / determinant],
    [(f * g - d * i) / determinant, (a * i - c * g) / determinant, (c * d - a * f) / determinant],
    [(d * h - e * g) / determinant, (b * g - a * h) / determinant, (a * e - b * d) / determinant],
  ];
}

function vectorMatrixMultiply(vector, matrix) {
  return [0, 1, 2].map(column => vector.reduce((sum, value, row) => sum + value * matrix[row][column], 0));
}

function fractionalToCartesian(fractional, lattice) {
  return [0, 1, 2].map(column => fractional.reduce(
    (sum, value, row) => sum + value * lattice[row][column], 0
  ));
}

function translatedCartesian(atom, translation, lattice) {
  const offset = fractionalToCartesian(translation, lattice);
  return atom.cart.map((value, index) => value + offset[index]);
}

function atomsAreBonded(left, right) {
  const dx = left.x - right.x;
  const dy = left.y - right.y;
  const dz = left.z - right.z;
  const distance = Math.hypot(dx, dy, dz);
  if (distance < .1) return false;
  const leftRadius = structureCovalentRadii[left.elem] || .9;
  const rightRadius = structureCovalentRadii[right.elem] || .9;
  return distance <= (leftRadius + rightRadius) * 1.25 + .15;
}

function buildPeriodicStructure(parsed) {
  const atomMap = new Map();
  const addAtom = (atomIndex, translation) => {
    const key = atomIndex + ":" + translation.join(",");
    if (atomMap.has(key)) return;
    const source = parsed.atoms[atomIndex];
    const [x, y, z] = translatedCartesian(source, translation, parsed.lattice);
    atomMap.set(key, {
      elem: source.element, x, y, z,
      chain: translation.every(value => value === 0) ? "C" : "P",
      color: parseInt((structureElementColors[source.element] || "#7f91ab").slice(1), 16),
      bonds: [], bondOrder: [],
    });
  };
  parsed.atoms.forEach((_, index) => addAtom(index, [0, 0, 0]));
  parsed.atoms.forEach((center, centerIndex) => {
    const centerCart = {elem: center.element, x: center.cart[0], y: center.cart[1], z: center.cart[2]};
    parsed.atoms.forEach((neighbor, neighborIndex) => {
      for (let a = -1; a <= 1; a += 1) for (let b = -1; b <= 1; b += 1) for (let c = -1; c <= 1; c += 1) {
        if (a === 0 && b === 0 && c === 0) continue;
        const [x, y, z] = translatedCartesian(neighbor, [a, b, c], parsed.lattice);
        if (atomsAreBonded(centerCart, {elem: neighbor.element, x, y, z})) addAtom(neighborIndex, [a, b, c]);
      }
    });
  });
  const atoms = Array.from(atomMap.values());
  for (let leftIndex = 0; leftIndex < atoms.length; leftIndex += 1) {
    for (let rightIndex = leftIndex + 1; rightIndex < atoms.length; rightIndex += 1) {
      if (!atomsAreBonded(atoms[leftIndex], atoms[rightIndex])) continue;
      atoms[leftIndex].bonds.push(rightIndex);
      atoms[leftIndex].bondOrder.push(1);
      atoms[rightIndex].bonds.push(leftIndex);
      atoms[rightIndex].bondOrder.push(1);
    }
  }
  return {atoms, centralCount: parsed.atoms.length, periodicCount: atoms.length - parsed.atoms.length};
}

function addStructureUnitCell(viewer, lattice) {
  const corners = [];
  for (let a = 0; a <= 1; a += 1) for (let b = 0; b <= 1; b += 1) for (let c = 0; c <= 1; c += 1) {
    const [x, y, z] = fractionalToCartesian([a, b, c], lattice);
    corners.push({a, b, c, x, y, z});
  }
  corners.forEach(corner => {
    [[1, 0, 0], [0, 1, 0], [0, 0, 1]].forEach(delta => {
      const end = corners.find(candidate =>
        candidate.a === corner.a + delta[0] && candidate.b === corner.b + delta[1] && candidate.c === corner.c + delta[2]
      );
      if (end) viewer.addLine({start: corner, end, color: "#77879b", linewidth: 1});
    });
  });
}

function createStructureAxisViewer(container) {
  materialStructureAxisViewer?.clear?.();
  container.replaceChildren();
  const viewer = window.$3Dmol.createViewer(container, {
    backgroundColor: "#ffffff",
    backgroundAlpha: 0,
    antialias: true,
    disableFog: true,
    orthographic: true,
    minimumZoomToDistance: 2.2,
  });
  viewer.setBackgroundColor("#ffffff", 0);
  const axes = [
    {label: "X", color: "#d92d2d", end: {x: 2, y: 0, z: 0}, unit: {x: 1, y: 0, z: 0}},
    {label: "Y", color: "#239044", end: {x: 0, y: 2, z: 0}, unit: {x: 0, y: 1, z: 0}},
    {label: "Z", color: "#315fc8", end: {x: 0, y: 0, z: 2}, unit: {x: 0, y: 0, z: 1}},
  ];
  axes.forEach(axis => {
    viewer.addArrow({
      start: {x: 0, y: 0, z: 0},
      end: axis.end,
      color: axis.color,
      radius: .075,
      radiusRatio: 2.2,
      mid: .76,
    });
    const label = document.createElement("span");
    label.className = `structure-axis-label structure-axis-label-${axis.label.toLowerCase()}`;
    label.textContent = axis.label;
    label.setAttribute("aria-hidden", "true");
    axis.labelElement = label;
    container.append(label);
  });
  viewer.updateStructureAxisLabels = quaternion => {
    if (!Array.isArray(quaternion) || quaternion.length < 4) return;
    const [qx, qy, qz, qw] = quaternion.map(Number);
    const norm = Math.hypot(qx, qy, qz, qw) || 1;
    const q = {x: qx / norm, y: qy / norm, z: qz / norm, w: qw / norm};
    const size = Math.min(container.clientWidth || 112, container.clientHeight || 112);
    const projectionScale = size * .17;
    const centerX = (container.clientWidth || size) / 2;
    const centerY = (container.clientHeight || size) / 2;
    const modelCenter = {x: 1, y: 1, z: 1};
    const labelOffset = .38;
    axes.forEach(axis => {
      const x = axis.end.x + axis.unit.x * labelOffset - modelCenter.x;
      const y = axis.end.y + axis.unit.y * labelOffset - modelCenter.y;
      const z = axis.end.z + axis.unit.z * labelOffset - modelCenter.z;
      const ix = q.w * x + q.y * z - q.z * y;
      const iy = q.w * y + q.z * x - q.x * z;
      const iz = q.w * z + q.x * y - q.y * x;
      const iw = -q.x * x - q.y * y - q.z * z;
      const rotatedX = ix * q.w + iw * -q.x + iy * -q.z - iz * -q.y;
      const rotatedY = iy * q.w + iw * -q.y + iz * -q.x - ix * -q.z;
      axis.labelElement.style.left = `${centerX + rotatedX * projectionScale}px`;
      axis.labelElement.style.top = `${centerY - rotatedY * projectionScale}px`;
    });
  };
  viewer.zoomTo();
  viewer.zoom(1.5);
  viewer.render();
  viewer.updateStructureAxisLabels([0, 0, 0, 1]);
  return viewer;
}

function structureViewModelAtoms(structureView) {
  return structureView.atoms.map(atom => ({
    elem: atom.element,
    x: Number(atom.x),
    y: Number(atom.y),
    z: Number(atom.z),
    chain: atom.central ? "C" : "P",
    color: parseInt((structureElementColors[atom.element] || "#7f91ab").slice(1), 16),
    bonds: atom.bonds.map(Number),
    bondOrder: atom.bonds.map(() => 1),
    properties: {
      siteIndex: atom.site_index,
      periodicImage: atom.image,
      sceneSource: structureView.source,
    },
  }));
}

function drawMaterialStructure(material, structure, structureView = null) {
  const container = document.querySelector("#structure-viewer");
  const axisContainer = document.querySelector("#structure-axis-viewer");
  if (!container || !structure?.content) return;
  const summary = document.querySelector("#material-structure-summary");
  const atomInfo = document.querySelector("#structure-atom-info");
  if (!window.$3Dmol) {
    container.innerHTML = "<p class='structure-error'>三维渲染组件未能加载。</p>";
    summary.textContent = "组件不可用";
    return;
  }

  const state = {style: "ball-stick", display: "periodic", unitCell: true};
  let parsedStructure;
  try {
    parsedStructure = parsePoscar(structure.content);
  } catch (error) {
    console.warn("自定义 POSCAR 解析失败，将使用基础查看模式。", error);
  }
  const baseAtomCount = Number(structureView?.central_count) || parsedStructure?.atoms.length || 0;
  if (baseAtomCount > 300) {
    state.display = "1";
    document.querySelector("#structure-supercell").value = "1";
    atomInfo.textContent = "该结构原胞超过 300 个原子，默认使用原胞模式以避免周期邻居搜索造成卡顿。";
  }
  const styleSpec = (color, periodicImage = false) => ({
    "ball-stick": {
      sphere: {radius: periodicImage ? .36 : .38, color, opacity: periodicImage ? .92 : 1},
      stick: {radius: periodicImage ? .07 : .08, color, opacity: periodicImage ? .86 : .96},
    },
    spacefill: {sphere: {scale: periodicImage ? .62 : .70, color, opacity: periodicImage ? .78 : 1}},
    stick: {stick: {radius: periodicImage ? .07 : .09, color, opacity: periodicImage ? .72 : .96}},
  })[state.style];

  const applyStructureStyle = (atoms, periodicMode = false) => {
    const elements = Array.from(new Set(atoms.map(atom => atom.elem).filter(Boolean)));
    elements.forEach(element => {
      const color = structureElementColors[element] || "#7f91ab";
      if (periodicMode) {
        materialStructureViewer.setStyle({elem: element, chain: "C"}, styleSpec(color, false));
        materialStructureViewer.setStyle({elem: element, chain: "P"}, styleSpec(color, true));
      } else {
        materialStructureViewer.setStyle({elem: element}, styleSpec(color, false));
      }
    });
  };

  try {
    materialStructureViewer?.clear?.();
    container.replaceChildren();
    materialStructureViewer = window.$3Dmol.createViewer(container, {
      backgroundColor: "#ffffff",
      antialias: true,
    });
  } catch (error) {
    container.innerHTML = "<p class='structure-error'>当前浏览器无法创建 WebGL 三维视图。</p>";
    summary.textContent = "WebGL 不可用";
    console.error(error);
    return;
  }

  try {
    materialStructureAxisViewer = axisContainer
      ? createStructureAxisViewer(axisContainer)
      : null;
  } catch (error) {
    materialStructureAxisViewer = null;
    console.warn("三维坐标轴渲染失败。", error);
  }

  const syncStructureAxisRotation = view => {
    if (!materialStructureAxisViewer || !axisContainer || !Array.isArray(view) || view.length < 8) return;
    const axisView = materialStructureAxisViewer.getView();
    materialStructureAxisViewer.setView([
      axisView[0], axisView[1], axisView[2], axisView[3],
      view[4], view[5], view[6], view[7],
    ], true);
    materialStructureAxisViewer.updateStructureAxisLabels?.(view.slice(4, 8));
    axisContainer.dataset.rotation = view.slice(4, 8).map(value => Number(value).toFixed(6)).join(",");
  };
  materialStructureViewer.setViewChangeCallback(syncStructureAxisRotation);

  const applyDefaultStructureView = () => {
    materialStructureViewer.setView?.([0, 0, 0, 0, 0, 0, 0, 1]);
    materialStructureViewer.zoomTo();
    materialStructureViewer.rotate(90, "z");
    materialStructureViewer.rotate(10, "x");
    materialStructureViewer.rotate(-8, "y");
    materialStructureViewer.zoom(1.0);
  };

  const rebuild = () => {
    try {
      materialStructureViewer.clear();
      let model;
      let periodicCount = 0;
      if (state.display === "periodic" && (structureView || parsedStructure)) {
        const periodic = structureView
          ? {
              atoms: structureViewModelAtoms(structureView),
              centralCount: Number(structureView.central_count),
              periodicCount: Number(structureView.periodic_count),
            }
          : buildPeriodicStructure(parsedStructure);
        model = materialStructureViewer.addModel();
        model.addAtoms(periodic.atoms);
        periodicCount = periodic.periodicCount;
      } else {
        model = materialStructureViewer.addModel(structure.content, "vasp");
        const repeat = Number(state.display);
        if (repeat > 1) {
        materialStructureViewer.replicateUnitCell(
            repeat, repeat, repeat, model, true
        );
        }
      }
      const atoms = materialStructureViewer.selectedAtoms({});
      applyStructureStyle(atoms, state.display === "periodic" && Boolean(structureView || parsedStructure));
      materialStructureViewer.setClickable({}, true, atom => {
        atomInfo.innerHTML = "<strong>" + escapeHtml(atom.elem || "未知元素") + "</strong> · " +
          "原子 #" + escapeHtml(Number(atom.index ?? 0) + 1) + " · 坐标 (" +
          [atom.x, atom.y, atom.z].map(value => Number(value).toFixed(3)).join(", ") + ") Å";
      });
      if (state.unitCell) {
        if (structureView?.lattice) addStructureUnitCell(materialStructureViewer, structureView.lattice);
        else if (parsedStructure) addStructureUnitCell(materialStructureViewer, parsedStructure.lattice);
        else materialStructureViewer.addUnitCell(model, {box: {color: "#7d8ba2", linewidth: 1}});
      }
      applyDefaultStructureView();
      materialStructureViewer.render();
      const atomCount = atoms.length;
      summary.textContent = state.display === "periodic"
        ? structure.format + " · 原胞 " + baseAtomCount + " + 周期邻居 " + periodicCount +
          (structureView?.source ? " · CrystalNN" : "")
        : structure.format + " · " + atomCount + " 原子" + (Number(state.display) > 1 ? " · " + state.display + "×超胞" : "");
      atomInfo.textContent = state.display === "periodic"
        ? "已补齐跨晶胞边界的周期配位；半透明原子为相邻晶胞镜像。点击原子可查看坐标。"
        : "点击原子可查看元素和笛卡尔坐标。";
      renderStructureElementLegend(atoms);
    } catch (error) {
      container.innerHTML = "<p class='structure-error'>结构解析失败：" + escapeHtml(error.message) + "</p>";
      summary.textContent = "解析失败";
      console.error(error);
    }
  };

  document.querySelector("#structure-style").addEventListener("change", event => {
    state.style = event.target.value;
    applyStructureStyle(
      materialStructureViewer.selectedAtoms({}),
      state.display === "periodic" && Boolean(structureView || parsedStructure),
    );
    materialStructureViewer.render();
  });
  document.querySelector("#structure-supercell").addEventListener("change", event => {
    const requested = event.target.value;
    const repeat = Number(requested);
    if (Number.isFinite(repeat) && baseAtomCount * repeat ** 3 > 3000) {
      event.target.value = String(state.display);
      atomInfo.textContent = "该材料生成此超胞后将超过 3000 个原子，已阻止以避免浏览器卡顿。";
      return;
    }
    state.display = requested;
    rebuild();
  });
  document.querySelector("#structure-unit-cell").addEventListener("change", event => {
    state.unitCell = event.target.checked;
    rebuild();
  });
  document.querySelector("#structure-reset").addEventListener("click", () => {
    applyDefaultStructureView();
    materialStructureViewer.render();
  });
  document.querySelector("#structure-snapshot").addEventListener("click", () => {
    const link = document.createElement("a");
    link.href = materialStructureViewer.pngURI();
    link.download = String(material.material_key || "structure").replaceAll(/[^a-zA-Z0-9._-]/g, "_") + ".png";
    link.click();
  });
  document.querySelector("#structure-fullscreen").addEventListener("click", async () => {
    const panel = document.querySelector("#structure-panel");
    if (document.fullscreenElement) await document.exitFullscreen();
    else await panel.requestFullscreen();
  });
  document.querySelector("#structure-settings-button").addEventListener("click", event => {
    const settings = document.querySelector("#structure-settings");
    settings.hidden = !settings.hidden;
    event.currentTarget.setAttribute("aria-expanded", String(!settings.hidden));
  });
  if (!structureFullscreenHandlerInstalled) {
    document.addEventListener("fullscreenchange", () => {
      window.setTimeout(() => {
        materialStructureViewer?.resize();
        materialStructureViewer?.render();
        materialStructureAxisViewer?.resize();
        materialStructureAxisViewer?.render();
        const axisView = materialStructureAxisViewer?.getView?.();
        if (axisView) materialStructureAxisViewer.updateStructureAxisLabels?.(axisView.slice(4, 8));
      }, 80);
    });
    structureFullscreenHandlerInstalled = true;
  }
  rebuild();
}

function renderStructureElementLegend(atoms) {
  const legend = document.querySelector("#structure-element-legend");
  if (!legend) return;
  const elements = new Map();
  atoms.forEach(atom => {
    if (!atom.elem || elements.has(atom.elem)) return;
    const numericColor = Number(atom.color);
    const fallback = {
      H: "#e7e7e7", C: "#8a8a8a", N: "#5f74c9", O: "#e84a3c",
      F: "#91a7d8", Si: "#d6ad8b", P: "#e58a37", S: "#e1c229",
      Cl: "#58a65c", Ag: "#b9b9b9", Au: "#d6a900",
    }[atom.elem] || "#7f91ab";
    elements.set(
      atom.elem,
      Number.isFinite(numericColor)
        ? "#" + numericColor.toString(16).padStart(6, "0").slice(-6)
        : fallback,
    );
  });
  legend.innerHTML = Array.from(elements, ([element, color]) =>
    "<span style='--element-color:" + escapeHtml(color) + "'>" + escapeHtml(element) + "</span>"
  ).join("");
}

function selectLandscapeMaterial(data) {
  const value = name => Number(data.properties[name]?.value);
  const shear = value("G_GPa");
  const bonding = value("E_tilde_GPa");
  const cte = value("CTE_ppm");
  if (![shear, bonding].every(Number.isFinite) || shear <= 0 || bonding <= 0) {
    clearLandscapeContext({replaceUrl: false});
    document.querySelector("#landscape-selection").textContent =
      "该材料缺少 Fig. 1d 坐标所需的 G 或论文定义 Ẽ=U_V/n。";
    return;
  }
  const point = {
    material_key: data.material.material_key,
    x_gpa: bonding,
    g_gpa: shear,
    classification: Number.isFinite(cte) && cte < 0 ? "NTE" : "PTE",
    source: "当前数据库",
    year: null,
    selected: true,
    context_origin: "database",
    database_key: data.material.material_key,
  };
  setLandscapeContext(point,
    "当前材料：" + data.material.material_key + " · Ẽ=" +
    point.x_gpa.toFixed(3) + " GPa · G=" + shear.toFixed(3) + " GPa");
}

function renderPrecisionThermalExpansion(result) {
  if (!result || !result.points || result.points.length < 2) {
    return "<section class='thermal-panel'><div class='thermal-heading'><h3>精确 QHA 热膨胀曲线</h3>" +
      "<p class='curve-note'>温度 T 与体热膨胀系数 α(T)</p></div>" +
      "<div class='thermal-empty'><p class='muted'>暂无已关联的精确 QHA 热膨胀曲线。</p>" +
      "<span>可通过 QHA 计算生成 α(T) 数据后在此对照晶体结构。</span></div></section>";
  }
  const warnings = Array.isArray(result.quality_warnings) && result.quality_warnings.length
    ? "质量提示：" + result.quality_warnings.join("；")
    : "该曲线来自已关联的精确 QHA 任务。";
  return "<section class='thermal-panel'><div class='thermal-heading'><h3>精确 QHA 热膨胀曲线</h3>" +
    "<p class='curve-note'>温度 T 与体热膨胀系数 α(T)</p></div>" +
    "<canvas id='thermal-curve' class='thermal-curve' width='720' height='440'></canvas>" +
    "<p class='curve-note'>任务 " + escapeHtml(result.job_id) + " · " + escapeHtml(warnings) + "</p></section>";
}

function drawPrecisionThermalExpansion(result, canvasSelector = "#thermal-curve") {
  if (!result || !result.points || result.points.length < 2) return;
  const canvas = document.querySelector(canvasSelector);
  if (!canvas) return;
  const {ctx, width, height} = prepareHiDpiCanvas(canvas);
  canvas.teRedraw = () => drawPrecisionThermalExpansion(result, canvasSelector);
  const points = result.points
    .filter(point => Number.isFinite(Number(point.temperature_k)) && Number.isFinite(Number(point.alpha_ppm_per_k)))
    .map(point => ({...point, temperature_k: Number(point.temperature_k), alpha_ppm_per_k: Number(point.alpha_ppm_per_k)}));
  if (points.length < 2) return;
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
  ctx.lineWidth = Math.max(.45, .8 * size / LANDSCAPE_REFERENCE_MARKER_SIZE);
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

function drawSelectedStar(ctx, x, y, scale = 1) {
  ctx.save();
  ctx.fillStyle = "#d7191c";
  ctx.strokeStyle = "#fff";
  ctx.lineWidth = 2.2 * scale;
  ctx.beginPath();
  for (let index = 0; index < 10; index++) {
    const radius = (index % 2 ? 5 : 11) * scale;
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

function landscapeMarkerScale(plotWidth, plotHeight) {
  const widthScale = plotWidth / LANDSCAPE_REFERENCE_PLOT.width;
  const heightScale = plotHeight / LANDSCAPE_REFERENCE_PLOT.height;
  return Math.max(.38, Math.min(2.4, Math.sqrt(widthScale * heightScale)));
}

function drawLandscape() {
  if (!fig1dReference) return;
  const canvas = document.querySelector("#landscape");
  const {ctx, width, height} = prepareHiDpiCanvas(canvas);
  canvas.teRedraw = drawLandscape;
  const margin = {left: 72, right: 22, top: 18, bottom: 64};
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const markerScale = landscapeMarkerScale(plotWidth, plotHeight);
  const markerSize = LANDSCAPE_REFERENCE_MARKER_SIZE * markerScale;
  canvas.dataset.markerSize = markerSize.toFixed(3);
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
    drawLandscapeMarker(ctx, point, pointX, pointY, markerSize, color);
    landscapeHitPoints.push({
      ...point,
      canvasX: pointX,
      canvasY: pointY,
      hitRadius: Math.max(7, markerSize * 1.9),
    });
  });

  if (selectedLandscapePoint && selectedLandscapePoint.x_gpa >= axis.x_min &&
      selectedLandscapePoint.x_gpa <= axis.x_max && selectedLandscapePoint.g_gpa >= axis.y_min &&
      selectedLandscapePoint.g_gpa <= axis.y_max) {
    const selectedX = x(selectedLandscapePoint.x_gpa);
    const selectedY = y(selectedLandscapePoint.g_gpa);
    drawSelectedStar(ctx, selectedX, selectedY, markerScale);
    landscapeHitPoints.unshift({
      ...selectedLandscapePoint,
      canvasX: selectedX,
      canvasY: selectedY,
      hitRadius: Math.max(10, 13 * markerScale),
    });
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
  ctx.fillText("Ẽ (GPa)", margin.left + plotWidth / 2, height - 9);
  ctx.save();
  ctx.translate(18, margin.top + plotHeight / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText("G (GPa)", 0, 0);
  ctx.restore();

  ctx.textAlign = "left";
  ctx.font = "13px Segoe UI";
  const legendX = margin.left + plotWidth - 195;
  const legendY = margin.top + plotHeight - 42;
  drawLandscapeMarker(ctx, {source: "Exp."}, legendX, legendY, LANDSCAPE_REFERENCE_MARKER_SIZE, "rgba(68,119,170,.9)");
  ctx.fillText("NTE", legendX + 10, legendY + 4);
  drawLandscapeMarker(ctx, {source: "DFT"}, legendX + 62, legendY, LANDSCAPE_REFERENCE_MARKER_SIZE, "rgba(253,56,39,.85)");
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
    const canvasX = event.clientX - rect.left - canvas.clientLeft;
    const canvasY = event.clientY - rect.top - canvas.clientTop;
    let nearest = null;
    let nearestDistance = Infinity;
    landscapeHitPoints.forEach(point => {
      const distance = Math.hypot(point.canvasX - canvasX, point.canvasY - canvasY);
      if (distance < nearestDistance) {
        nearestDistance = distance;
        nearest = point;
      }
    });
    if (!nearest || nearestDistance > nearest.hitRadius) {
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

function landscapeJumpAction(message) {
  return "<div class='context-jump-action'><span>" + escapeHtml(message) +
    "</span><button type='button' data-context-action='landscape'>在景观中定位</button></div>";
}

function selectPredictedLandscapePoint(filename, shear, bonding, classification, source) {
  const point = {
    material_key: filename,
    x_gpa: Number(bonding),
    g_gpa: Number(shear),
    classification: String(classification).includes("pte") && !String(classification).includes("nte") ? "PTE" : "NTE",
    source,
    year: null,
    selected: true,
    context_origin: "predict",
  };
  setLandscapeContext(point,
    "当前预测：" + filename + " · Ẽ=" + Number(bonding).toFixed(3) +
    " GPa · G=" + Number(shear).toFixed(3) + " GPa");
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
    "；建议：" + escapeHtml(result.recommended_next_step) + "</p>" +
    landscapeJumpAction("快速预测已生成 G–Ẽ 坐标，可立即查看分类位置。");
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
      escapeHtml(result.quality_warnings.join("；")) + "</p>" : "") +
    landscapeJumpAction("精准弹性结果已生成 G–Ẽ 坐标，可与论文材料直接比较。");
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
  const {ctx, width, height} = prepareHiDpiCanvas(canvas);
  canvas.teRedraw = () => drawZteCurves(result);
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
  restoreLandscapeContext();
  restoreComparisonMaterials();
  renderComparisonSelection();
  setupMaterialContext();
  setupWorkspaceNavigation();
  setupElementFilter();
  try {
    const results = await Promise.all([
      loadStats(),
      loadPeriodicElementCounts(),
      searchMaterials(),
      api("/static/fig1d-reference.json"),
      loadAbout(),
    ]);
    fig1dReference = results[3];
    try {
      await restoreLandscapeContextFromLocation();
    } catch (error) {
      console.warn("无法从链接恢复景观材料", error);
      document.querySelector("#landscape-selection").textContent = "链接中的材料无法加载。";
    }
    drawLandscape();
  } catch (error) {
    document.querySelector("#health-status").textContent = "服务异常";
    console.error(error);
  }
  setupLandscapeInteraction();
  document.querySelector("#search-button").addEventListener("click", searchMaterials);
  document.querySelector("#search-input").addEventListener("keydown", event => {
    if (event.key === "Enter") searchMaterials();
  });
  ["#material-sort-by", "#material-sort-order", "#material-cte-filter", "#material-limit"]
    .forEach(selector => document.querySelector(selector).addEventListener("change", searchMaterials));
  document.querySelector("#material-compare-run").addEventListener("click", loadMaterialComparison);
  document.querySelector("#material-compare-clear").addEventListener("click", () => {
    comparisonMaterialKeys = [];
    persistComparisonMaterials();
    renderComparisonSelection();
    const result = document.querySelector("#material-compare-result");
    result.className = "compare-result placeholder";
    result.textContent = "至少收藏两个材料后即可生成对比。";
  });
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
  const setAgentCollapsed = collapsed => {
    agentWidget.classList.toggle("collapsed", collapsed);
    agentToggle.textContent = collapsed ? "+" : "−";
    agentToggle.setAttribute("aria-expanded", String(!collapsed));
    agentToggle.setAttribute("aria-label", collapsed ? "展开 Agent" : "最小化 Agent");
  };
  if (window.matchMedia("(max-width: 560px)").matches) setAgentCollapsed(true);
  agentToggle.addEventListener("click", () => {
    setAgentCollapsed(!agentWidget.classList.contains("collapsed"));
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

  function renderAgentAttachment() {
    const container = document.querySelector("#agent-attachment");
    if (!agentAttachments.length) {
      container.hidden = true;
      document.querySelector("#agent-attachment-name").textContent = "";
      return;
    }
    const attachment = agentAttachments[0];
    document.querySelector("#agent-attachment-name").textContent =
      `${attachment.filename} · ${attachment.inspection.atom_count ?? "?"} atoms`;
    container.hidden = false;
  }

  document.querySelector("#agent-attachment-clear").addEventListener("click", () => {
    agentAttachments = [];
    document.querySelector("#agent-file").value = "";
    renderAgentAttachment();
  });

  document.querySelector("#agent-file").addEventListener("change", async event => {
    const file = event.target.files?.[0];
    if (!file) return;
    const uploadNotice = appendAgentMessage("assistant", "正在检查并附加结构…", "pending");
    const body = new FormData();
    body.append("file", file);
    try {
      const uploaded = await api("/api/agent/structures", {method: "POST", body});
      agentAttachments = [uploaded];
      renderAgentAttachment();
      uploadNotice.classList.remove("pending");
      uploadNotice.textContent =
        `已附加 ${file.name}，结构格式 ${uploaded.inspection.format.toUpperCase()}，` +
        `${uploaded.inspection.atom_count ?? "?"} 个原子。你可以直接要求我计算热膨胀。`;
    } catch (error) {
      uploadNotice.classList.remove("pending");
      uploadNotice.textContent = error.message;
      agentAttachments = [];
      renderAgentAttachment();
    }
  });

  async function pollAgentCalculation(jobId, bubble) {
    try {
      const job = await api("/api/precision/jobs/" + encodeURIComponent(jobId));
      const percent = Number.isFinite(Number(job.progress?.percent))
        ? ` · ${job.progress.percent}%` : "";
      const jobLabel = {
        fast_structure_screening: "快速预测",
        precision_elastic: "精准弹性",
        precision_qha: "QHA",
      }[job.workflow] || "计算";
      bubble.textContent = `${jobLabel}任务 ${job.id}\n状态：${job.status}${percent}`;
      if (["PENDING", "QUEUED", "RUNNING"].includes(job.status)) {
        window.setTimeout(() => pollAgentCalculation(jobId, bubble), 3000);
        return;
      }
      if (job.status !== "SUCCEEDED") {
        bubble.textContent += `\n${job.error_message || "计算失败，请检查任务日志。"}`;
        return;
      }
      const result = job.result;
      if (job.workflow === "fast_structure_screening") {
        const fast = result.fast_sbr;
        bubble.classList.add("wide");
        bubble.innerHTML =
          "<strong>快速热膨胀倾向预测完成</strong>" +
          "<p>预测 G：" + numeric(fast.predicted_shear_modulus_gpa) + " GPa<br>" +
          "键合模量 Ẽ：" + numeric(fast.bonding.bonding_modulus_gpa) + " GPa<br>" +
          "ξ：" + numeric(fast.sbr.xi) + "<br>" +
          "结论：" + escapeHtml(classificationText(fast.sbr.classification)) + "</p>" +
          "<span class='agent-tool-summary'>" +
          escapeHtml(fast.recommended_next_step || "可进一步进行弹性或QHA验证") + "</span>";
        return;
      }
      if (job.workflow === "precision_elastic") {
        bubble.classList.add("wide");
        bubble.innerHTML =
          "<strong>精准弹性预测完成</strong>" +
          "<p>Hill G：" + numeric(result.shear_modulus_hill_gpa) + " GPa<br>" +
          "键合模量 Ẽ：" + numeric(result.bonding.bonding_modulus_gpa) + " GPa<br>" +
          "ξ：" + numeric(result.sbr.xi) + "<br>" +
          "结论：" + escapeHtml(classificationText(result.sbr.classification)) + "</p>" +
          (result.quality_warnings?.length
            ? "<span class='agent-tool-summary'>质量提示：" +
              escapeHtml(result.quality_warnings.join("；")) + "</span>"
            : "");
        return;
      }
      const canvasId = "agent-job-curve-" + job.id;
      bubble.classList.add("wide");
      bubble.innerHTML =
        "<strong>QHA 热膨胀计算完成</strong>" +
        "<p>300 K：" + numeric(result.alpha_300k_ppm_per_k) + " ppm/K · " +
        escapeHtml(String(result.thermal_expansion_curve?.length || 0)) + " 个温度点</p>" +
        "<canvas id='" + canvasId + "' class='agent-job-curve' width='720' height='300'></canvas>";
      drawPrecisionThermalExpansion(
        {points: result.thermal_expansion_curve.map(point => ({
          temperature_k: point[0],
          alpha_ppm_per_k: point[1] * 1_000_000,
        }))},
        "#" + canvasId,
      );
    } catch (error) {
      bubble.textContent = error.message;
    }
  }

  function appendAgentApproval(approval) {
    const bubble = appendAgentMessage("assistant", "", "wide");
    const card = document.createElement("div");
    card.className = "agent-approval-card";
    const title = document.createElement("strong");
    const modeLabel = {
      fast: "快速预测",
      elastic: "精准弹性预测",
      qha: "QHA 热膨胀计算",
    }[approval.mode] || "结构计算";
    title.textContent = "需要确认：提交" + modeLabel;
    const summary = document.createElement("div");
    summary.textContent = approval.summary;
    const actions = document.createElement("div");
    actions.className = "agent-approval-actions";
    const approveButton = document.createElement("button");
    approveButton.type = "button";
    approveButton.textContent = "确认并提交";
    const rejectButton = document.createElement("button");
    rejectButton.type = "button";
    rejectButton.className = "reject";
    rejectButton.textContent = "取消";
    actions.append(approveButton, rejectButton);
    card.append(title, summary, actions);
    bubble.appendChild(card);

    approveButton.addEventListener("click", async () => {
      approveButton.disabled = true;
      rejectButton.disabled = true;
      approveButton.textContent = "正在提交…";
      try {
        const result = await api(
          "/api/agent/approvals/" + encodeURIComponent(approval.approval_id) + "/approve",
          {method: "POST"},
        );
        bubble.textContent = `已批准并提交 QHA 任务：${result.job.id}`;
        agentHistory.push({
          role: "assistant",
          content: `用户已批准${modeLabel}，任务job_id=${result.job.id}，后续可查询任务进度。`,
        });
        agentHistory = agentHistory.slice(-12);
        window.setTimeout(() => pollAgentCalculation(result.job.id, bubble), 800);
      } catch (error) {
        approveButton.disabled = false;
        rejectButton.disabled = false;
        approveButton.textContent = "确认并提交";
        summary.textContent = error.message;
      }
    });

    rejectButton.addEventListener("click", async () => {
      approveButton.disabled = true;
      rejectButton.disabled = true;
      try {
        await api(
          "/api/agent/approvals/" + encodeURIComponent(approval.approval_id) + "/reject",
          {method: "POST"},
        );
        bubble.textContent = "已取消本次 QHA 计算请求。";
      } catch (error) {
        summary.textContent = error.message;
      }
    });
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
        body: JSON.stringify({
          message,
          history: agentHistory,
          attachments: agentAttachments.map(item => item.structure_id),
        }),
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
      (result.tool_calls || [])
        .map(item => item.result)
        .filter(item => item?.approval_required)
        .forEach(appendAgentApproval);
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

let canvasResizeTimer = null;
window.addEventListener("resize", () => {
  window.clearTimeout(canvasResizeTimer);
  canvasResizeTimer = window.setTimeout(() => {
    document.querySelectorAll("canvas").forEach(canvas => canvas.teRedraw?.());
  }, 120);
});

initialize();
