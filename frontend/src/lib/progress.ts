import type { SseEvent } from "../types/api";

// 由 SSE 事件流推导每个 Agent 步骤的状态，供进度列表渲染。
export type StepState =
  | { status: "pending"; node: string; label: string }
  | { status: "running"; node: string; label: string; attempt: number }
  | { status: "done"; node: string; label: string; attempt: number };

// 需要展示执行细节的节点及其中文名，与后端 NodeEventReporter._KNOWN_NODES 一致。
export const STEP_LABELS: Record<string, string> = {
  extract_policy: "解构政策",
  expand_chain: "扩展产业链",
  match_companies: "匹配受益公司",
  broaden_match: "放宽匹配重试",
  form_candidate: "生成核验候选",
  gather_evidence: "检索证据",
  broaden_evidence: "放宽检索重试",
  adversarial_check: "对抗式核验",
  assemble_graph: "装配图谱",
};

function nodeLabel(node: string): string {
  return STEP_LABELS[node] ?? node;
}

export function deriveSteps(events: SseEvent[]): StepState[] {
  const order: string[] = [];
  const started = new Set<string>();
  const done = new Set<string>();
  const attempts = new Map<string, number>();

  for (const event of events) {
    const node = event.node;
    if (!node || node === "analysis_start" || node === "analysis_complete") continue;
    if (!order.includes(node)) order.push(node);
    if (event.type.endsWith("_start")) {
      started.add(node);
      attempts.set(node, event.attempt ?? 1);
    }
    if (event.type.endsWith("_end")) {
      done.add(node);
      if (event.attempt) attempts.set(node, event.attempt);
    }
  }

  return order.map((node) => {
    const label = nodeLabel(node);
    const attempt = attempts.get(node) ?? 1;
    if (done.has(node)) return { status: "done", node, label, attempt };
    if (started.has(node)) return { status: "running", node, label, attempt };
    return { status: "pending", node, label };
  });
}

export function overallProgress(events: SseEvent[]): {
  done: number;
  total: number;
} {
  // 取最近事件的 total；done 以已结束节点数为准。
  let total = 0;
  for (const event of events) {
    if (event.progress && event.progress.total > 0) {
      total = event.progress.total;
    }
  }
  const done = deriveSteps(events).filter((s) => s.status === "done").length;
  return { done, total };
}
