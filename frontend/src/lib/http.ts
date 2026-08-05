import type {
  AnalysisRequest,
  AnalysisTask,
  GraphPayload,
  Company,
  PolicyImportPayload,
  PolicyImportResult,
  PolicyLineage,
  PolicyListResponse,
  PolicyStats,
  TaskAccepted,
} from "../types/api";

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) || "";

export function apiUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  const base = BASE.replace(/\/$/, "");
  const suffix = path.startsWith("/") ? path : `/${path}`;
  return `${base}${suffix}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(apiUrl(path), init);
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

export function fetchCompany(companyId: string): Promise<Company> {
  return request<Company>(`/api/v1/companies/${encodeURIComponent(companyId)}`);
}

export function reportUrl(taskId: string): string {
  return apiUrl(`/api/v1/reports/${taskId}.md`);
}

export interface PolicyQuery {
  q?: string;
  authority_level?: string;
  document_type?: string;
  lifecycle_status?: string;
  authenticity_grade?: string;
  industry?: string;
  region?: string;
}

export function fetchPolicies(query: PolicyQuery = {}): Promise<PolicyListResponse> {
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  const suffix = params.size ? `?${params.toString()}` : "";
  return request<PolicyListResponse>(`/api/v1/policies${suffix}`);
}

export function fetchPolicyLineage(policyId: string): Promise<PolicyLineage> {
  return request<PolicyLineage>(
    `/api/v1/policies/${encodeURIComponent(policyId)}/lineage`
  );
}

export function fetchPolicyStats(): Promise<PolicyStats> {
  return request<PolicyStats>("/api/v1/policies/stats");
}

export function importPolicyHtml(
  payload: PolicyImportPayload
): Promise<PolicyImportResult> {
  return request<PolicyImportResult>("/api/v1/policy-imports/html", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function analyzeCatalogPolicy(policyId: string): Promise<TaskAccepted> {
  return request<TaskAccepted>(
    `/api/v1/policies/${encodeURIComponent(policyId)}/analyses`,
    { method: "POST" }
  );
}
