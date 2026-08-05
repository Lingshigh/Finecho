// 与后端 FinEcho API 契约一一对应的类型定义。

export type TaskStatus = "queued" | "running" | "succeeded" | "failed";

export type NodeType = "policy" | "industry" | "supply_chain" | "company";

export type VerdictKind = "high_confidence" | "watch" | "hotspot_risk";

// ---- SSE 事件 ----
export type SseEventType =
  | "analysis_start"
  | `node_${string}_start`
  | `node_${string}_end`
  | "analysis_complete"
  | "analysis_failed";

export interface SseEvent {
  task_id: string;
  type: SseEventType;
  node?: string;
  label?: string;
  attempt?: number;
  detail?: string;
  progress?: { completed: string[]; total: number };
  at?: string;
}

// ---- 任务与图谱 ----
export interface GraphNode {
  id: string;
  label: string;
  type: NodeType;
  level: number;
  properties?: Record<string, unknown>;
}

export interface GraphEdge {
  source: string;
  target: string;
  relation: string;
  weight?: number;
  evidence_ids?: string[];
}

export interface GraphPayload {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface Evidence {
  id: string;
  company_id: string;
  source_type: string;
  title: string;
  excerpt: string;
  year?: number | null;
  source_url?: string | null;
  relevance: number;
}

export interface Verdict {
  company_id: string;
  company_name: string;
  ticker: string;
  verdict: VerdictKind;
  benefit_probability: number;
  divergence_score: number;
  revenue_exposure: number;
  reasons: string[];
  evidence: Evidence[];
}

export interface AnalysisResult {
  task_id: string;
  policy_summary: string;
  policy_keywords: string[];
  nodes: GraphNode[];
  edges: GraphEdge[];
  verdicts: Verdict[];
  warnings: string[];
  generated_at: string;
}

export interface AnalysisTask {
  task_id: string;
  status: TaskStatus;
  created_at: string;
  updated_at: string;
  request: {
    policy_title: string;
    policy_text: string;
    max_depth?: number;
  };
  result: AnalysisResult | null;
  error: string | null;
}

export interface TaskAccepted {
  task_id: string;
  status: TaskStatus;
  poll_url: string;
  events_url: string;
}

export interface AnalysisRequest {
  policy_title: string;
  policy_text: string;
  max_depth?: number;
  lenient_matching?: boolean;
}

// ---- 前端状态机 ----
export type Phase = "idle" | "submitting" | "running" | "complete" | "failed";
