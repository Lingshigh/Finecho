import { useEffect, useMemo } from "react";
import {
  AnalysisContext,
  useAnalysisContext,
  type AnalysisContextValue,
} from "../contexts/AnalysisContext";
import { useAnalysis } from "../hooks/useAnalysis";
import { useGraph } from "../hooks/useGraph";
import SubmitPanel from "../components/workbench/SubmitPanel";
import ProgressStream from "../components/workbench/ProgressStream";
import GraphCanvas from "../components/workbench/GraphCanvas";
import VerdictBoard from "../components/workbench/VerdictBoard";

export default function Workbench() {
  const { state, submit, restore, reset } = useAnalysis();

  const value = useMemo<AnalysisContextValue>(
    () => ({
      phase: state.phase,
      taskId: state.taskId,
      events: state.events,
      task: state.task,
      error: state.error,
      submit,
      restore,
      reset,
    }),
    [state, submit, restore, reset]
  );

  // 刷新恢复：URL 带 ?task= 时直接按任务 ID 恢复（轮询，不重开 SSE）。
  const urlParams = new URLSearchParams(window.location.search);
  const restoreTaskId = urlParams.get("task");
  useEffect(() => {
    if (restoreTaskId && state.phase === "idle") {
      restore(restoreTaskId);
    }
  }, [restoreTaskId, state.phase, restore]);

  return (
    <AnalysisContext.Provider value={value}>
      <div className="workbench">
        <header className="workbench-header container">
          <a href="/" className="workbench-logo">
            FinEcho
          </a>
          {state.taskId && (
            <button className="workbench-reset" onClick={reset}>
              新分析
            </button>
          )}
        </header>
        <main className="workbench-main container">
          <SubmitPanel />
          <ProgressStream />
          <Results />
        </main>
      </div>
    </AnalysisContext.Provider>
  );
}

function Results() {
  const { phase, taskId, task } = useAnalysisContext();
  const graph = useGraph(phase === "complete" ? taskId : null);
  const verdicts = task?.result?.verdicts ?? [];

  if (phase !== "complete") return null;

  return (
    <div className="results">
      {task?.result && (
        <div className="result-summary">
          <h2 className="section-title">分析结果</h2>
          <p className="result-summary-text">{task.result.policy_summary}</p>
          {task.result.policy_keywords.length > 0 && (
            <div className="result-keywords">
              {task.result.policy_keywords.map((kw: string) => (
                <span key={kw} className="keyword-chip">
                  {kw}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      <section className="graph-section">
        <div className="section-head">
          <h2 className="section-title">产业链影响图谱</h2>
        </div>
        {graph.payload && graph.layout ? (
          <GraphCanvas
            payload={graph.payload}
            layout={graph.layout}
            verdicts={verdicts}
            loading={graph.loading}
            error={graph.error}
          />
        ) : (
          <div className="graph-loading">
            {graph.loading ? "图谱加载中…" : graph.error ?? "加载中…"}
          </div>
        )}
      </section>

      <VerdictBoard />
    </div>
  );
}
