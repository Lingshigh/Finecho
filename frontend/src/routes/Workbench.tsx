import { useEffect, useMemo } from "react";
import { Link } from "react-router-dom";
import {
  AnalysisContext,
  useAnalysisContext,
  type AnalysisContextValue,
} from "../contexts/AnalysisContext";
import { useAnalysis } from "../hooks/useAnalysis";
import { useGraph } from "../hooks/useGraph";
import SubmitPanel from "../components/workbench/SubmitPanel";
import { reportUrl } from "../lib/http";
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

  if (phase === "failed") return <VerdictBoard />;
  if (phase !== "complete") return null;

  return (
    <div className="results">
      {task?.result && (
        <div className="result-summary">
          <h2 className="section-title">分析结果</h2>
          {taskId && (
            <a className="report-link" href={reportUrl(taskId)} download>
              下载 Markdown 简报
            </a>
          )}
          {taskId && (
            <Link className="report-link" to={`/report?task=${taskId}`}>
              查看完整产业研报 →
            </Link>
          )}
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
          {task.result.warnings.length > 0 && (
            <div className="result-warnings">
              <strong>风险提示</strong>
              <ul>
                {task.result.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </div>
          )}
          <div className="result-meta">
            <span>生成于 {new Date(task.result.generated_at).toLocaleString("zh-CN")}</span>
            {task.request.source_url && (
              <a
                href={task.request.source_url}
                target="_blank"
                rel="noreferrer"
              >
                查看政策来源
              </a>
            )}
          </div>
        </div>
      )}

      {task?.result?.report && (
        <div className="report-inline-note">
          已生成完整产业研报，
          <Link to={`/report?task=${taskId}`}>点击查看 →</Link>
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
