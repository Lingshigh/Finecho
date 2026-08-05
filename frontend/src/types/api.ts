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
  revenue_exposure: number | null;
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
  request: AnalysisRequest;
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
  source_url?: string | null;
  target_companies?: string[];
  max_depth?: 1 | 2 | 3;
  lenient_matching?: boolean;
}

export interface Company {
  id: string;
  ticker: string;
  name: string;
  industries: string[];
  products: string[];
  revenue_exposure: number;
  rd_ratio: number;
  capacity_constraint: string;
  financials?: Record<string, string | number | null>;
}


// ---- 前端状态机 ----
export type Phase = "idle" | "submitting" | "running" | "complete" | "failed";

// ---- 政策事实库 ----
export type AuthorityLevel =
  | "central"
  | "state_council"
  | "ministry"
  | "province"
  | "city"
  | "county"
  | "unknown";

export type PolicyDocumentType =
  | "law"
  | "regulation"
  | "opinion"
  | "notice"
  | "plan"
  | "measure"
  | "standard"
  | "announcement"
  | "interpretation"
  | "draft"
  | "news"
  | "other";

export type PolicyLifecycleStatus =
  | "draft"
  | "effective"
  | "amended"
  | "repealed"
  | "expired"
  | "unknown";

export type AuthenticityGrade = "A" | "B" | "C" | "quarantined";

export interface EvidenceQuote {
  excerpt: string;
  clause_ref?: string | null;
  source_url?: string | null;
}

export type PolicyAgentName =
  | "document_understanding"
  | "scope_extraction"
  | "impact_analysis"
  | "relation_reasoning";

export interface PolicyAgentRun {
  agent: PolicyAgentName;
  status: "completed" | "fallback" | "failed";
  mode: "rule" | "llm" | "hybrid";
  summary: string;
  confidence: number;
  evidence_count: number;
  duration_ms: number;
  warnings: string[];
}

export interface PolicyClause {
  id: string;
  order: number;
  heading: string;
  text: string;
}

export interface PolicyScope {
  regions: string[];
  industries: string[];
  target_entities: string[];
  project_stages: string[];
  conditions: string[];
  exclusions: string[];
  valid_from?: string | null;
  valid_until?: string | null;
  evidence: EvidenceQuote[];
  confidence: number;
}

export interface PolicyImpact {
  id: string;
  title: string;
  direction: "support" | "restrict" | "mandatory" | "neutral";
  action: string;
  target: string;
  summary: string;
  industries: string[];
  chain_nodes: string[];
  evidence: EvidenceQuote[];
  confidence: number;
  review_status: "pending" | "reviewed" | "rejected";
}

export interface PolicyDocument {
  id: string;
  title: string;
  document_number?: string | null;
  issuing_authorities: string[];
  authority_level: AuthorityLevel;
  document_type: PolicyDocumentType;
  lifecycle_status: PolicyLifecycleStatus;
  publish_date?: string | null;
  effective_date?: string | null;
  expiry_date?: string | null;
  source_name: string;
  source_url?: string | null;
  attachment_url?: string | null;
  authenticity_grade: AuthenticityGrade;
  is_red_head?: boolean | null;
  summary: string;
  content: string;
  clauses: PolicyClause[];
  scope: PolicyScope;
  impacts: PolicyImpact[];
  agent_runs: PolicyAgentRun[];
  keywords: string[];
  quality_warnings: string[];
  imported_at: string;
}

export interface PolicyRelation {
  source_id: string;
  target_id: string;
  relation:
    | "based_on"
    | "implements"
    | "localizes"
    | "interprets"
    | "cites"
    | "supersedes"
    | "repeals"
    | "overlaps"
    | "conflicts_with";
  confidence: number;
  evidence?: string | null;
}

export interface PolicyLineage {
  center_id: string;
  nodes: PolicyDocument[];
  edges: PolicyRelation[];
}

export interface PolicyFacets {
  authority_levels: Record<string, number>;
  document_types: Record<string, number>;
  lifecycle_statuses: Record<string, number>;
  authenticity_grades: Record<string, number>;
  industries: Record<string, number>;
  regions: Record<string, number>;
}

export interface PolicyListResponse {
  items: PolicyDocument[];
  total: number;
  page: number;
  page_size: number;
  facets: PolicyFacets;
}

export interface PolicyStats {
  total: number;
  formal_documents: number;
  pending_review: number;
  quarantined: number;
  central_documents: number;
  local_documents: number;
}

export interface PolicyDocumentImportPayload {
  title: string;
  content: string;
  source_name: string;
  authority_name: string;
  source_url?: string;
  default_authority_level: AuthorityLevel;
  persist: boolean;
}

export interface PolicyAgentAnalysisResponse {
  document: PolicyDocument;
  relations: PolicyRelation[];
  persisted: boolean;
}

export interface PolicyAgentStatus {
  enabled: boolean;
  llm_configured: boolean;
  execution_strategy: string;
  agents: PolicyAgentName[];
}

export interface PolicyImportPayload {
  source_name: string;
  authority_name: string;
  html: string;
  source_url?: string;
  default_authority_level: AuthorityLevel;
}

export interface PolicyImportResult {
  imported: number;
  updated: number;
  quarantined: number;
  documents: PolicyDocument[];
  quarantine_items: { title: string; url?: string | null; reason: string }[];
}
