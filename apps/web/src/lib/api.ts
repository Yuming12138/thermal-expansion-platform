/**
 * 后端 API 访问的最小封装。
 *
 * 契约现状：OpenAPI 响应模型尚未定稿（重构方案阶段 2），因此这里只提供
 * 传输层（错误归一、JSON 解析、超时），不声明业务响应类型。
 * 契约定稿后由 openapi-typescript 生成的类型替换 `unknown`。
 *
 * 旧版 app.js 的 `api()` 无超时、无中断；长耗时任务轮询曾出现永久 pending，
 * 超时是本次重构明确要修复的点，故从一开始就内置。
 */

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const DEFAULT_TIMEOUT_MS = 15_000;

export async function api(path: string, init: RequestInit = {}, timeoutMs = DEFAULT_TIMEOUT_MS): Promise<unknown> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(path, { ...init, signal: controller.signal });
    if (!response.ok) {
      let detail = `${response.status} ${response.statusText}`;
      try {
        const body: unknown = await response.json();
        const serverDetail = (body as { detail?: unknown }).detail;
        if (typeof serverDetail === "string" && serverDetail.length > 0) {
          detail = serverDetail;
        }
      } catch {
        /* 非 JSON 错误体，保留状态码信息 */
      }
      throw new ApiError(response.status, detail);
    }
    if (response.status === 204) return null;
    return (await response.json()) as unknown;
  } finally {
    window.clearTimeout(timer);
  }
}

export interface BackendHealth {
  online: boolean;
  version: string | null;
}

/** 连通性探测：只报告在线与否与版本号，不假设响应结构。 */
export async function fetchBackendHealth(): Promise<BackendHealth> {
  try {
    const body = (await api("/api/health", { method: "GET" }, 5_000)) as { version?: unknown };
    const version = typeof body?.version === "string" ? body.version : null;
    return { online: true, version };
  } catch {
    return { online: false, version: null };
  }
}
