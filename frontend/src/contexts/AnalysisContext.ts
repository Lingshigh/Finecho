import { createContext, useContext } from "react";
import type { AnalysisRequest, AnalysisTask, Phase, SseEvent } from "../types/api";

// 工作台共享上下文：SubmitPanel / ProgressStream / GraphCanvas / VerdictBoard 都要读同一份分析状态。
export interface AnalysisContextValue {
  phase: Phase;
  taskId: string | null;
  events: SseEvent[];
  task: AnalysisTask | null;
  error: string | null;
  submit: (request: AnalysisRequest) => Promise<void>;
  restore: (taskId: string) => void;
  reset: () => void;
}

export const AnalysisContext = createContext<AnalysisContextValue | null>(null);

export function useAnalysisContext(): AnalysisContextValue {
  const ctx = useContext(AnalysisContext);
  if (!ctx) throw new Error("useAnalysisContext 必须在 AnalysisProvider 内使用");
  return ctx;
}
