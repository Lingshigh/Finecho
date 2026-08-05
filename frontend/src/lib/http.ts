import type {
  AnalysisRequest,
  AnalysisTask,
  GraphPayload,
  TaskAccepted,
} from "../types/api";

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) || "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init);
  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body?.message) message = body.message;
    } catch {
      /* 忽略非 JSON 错误体 */
    }
    throw new Error(message);
  }
  return res.json() as Promise<T>;
}

export function submitAnalysis(payload: AnalysisRequest): Promise<TaskAccepted> {
  return request<TaskAccepted>("/api/v1/analyses", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function fetchTask(taskId: string): Promise<AnalysisTask> {
  return request<AnalysisTask>(`/api/v1/analyses/${taskId}`);
}

export function fetchGraph(taskId: string): Promise<GraphPayload> {
  return request<GraphPayload>(`/api/v1/graphs/${taskId}`);
}

export function reportUrl(taskId: string): string {
  return `${BASE}/api/v1/reports/${taskId}.md`;
}
