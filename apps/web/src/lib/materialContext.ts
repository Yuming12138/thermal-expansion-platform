/**
 * 材料上下文（签名细节）：在任意工作区选中的当前材料，跨工作区与刷新保持。
 *
 * 存储键沿用旧版 `tep.material-context.v1`，保证新旧前端交替期间上下文不丢。
 * 旧版写入的确切字段结构未知，故解析采取防御式读取：只挑选已知字段并校验类型。
 */

export type MaterialClassification = "nte" | "pte";

export interface MaterialContext {
  materialKey: string;
  formula: string;
  classification?: MaterialClassification;
}

const STORAGE_KEY = "tep.material-context.v1";

function parseContext(raw: string | null): MaterialContext | null {
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) return null;
    const record = parsed as Record<string, unknown>;
    const materialKey = typeof record.materialKey === "string" ? record.materialKey : typeof record.material_key === "string" ? record.material_key : "";
    const formula = typeof record.formula === "string" ? record.formula : "";
    if (!materialKey && !formula) return null;
    const classification = record.classification === "nte" || record.classification === "pte" ? record.classification : undefined;
    return { materialKey, formula, classification };
  } catch {
    return null;
  }
}

export function loadMaterialContext(): MaterialContext | null {
  try {
    return parseContext(window.localStorage.getItem(STORAGE_KEY));
  } catch {
    return null;
  }
}

export function saveMaterialContext(context: MaterialContext | null): void {
  try {
    if (context === null) {
      window.localStorage.removeItem(STORAGE_KEY);
    } else {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(context));
    }
  } catch {
    /* 隐私模式等场景下静默降级为会话内状态 */
  }
}
