import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import ReportBlock from "../components/workbench/ReportBlock";
import { fetchTask, reportUrl } from "../lib/http";
import type { AnalysisTask, IndustryReport } from "../types/api";

export default function Report() {
  const [taskId, setTaskId] = useState<string | null>(null);
  const [task, setTask] = useState<AnalysisTask | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setTaskId(params.get("task"));
  }, []);

  useEffect(() => {
    if (!taskId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchTask(taskId)
      .then((result) => {
        if (cancelled) return;
        setTask(result);
      })
      .catch((reason: Error) => !cancelled && setError(reason.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [taskId]);

  const report: IndustryReport | null = task?.result?.report ?? null;
  const taskSucceeded = task?.status === "succeeded";

  return (
    <div className="workbench">
      <main className="workbench-main container">
        <div className="results">
          {loading && <p className="report-page-note">产业研究报告加载中…</p>}
          {!loading && error && <p className="report-page-note">研报加载失败：{error}</p>}
          {!loading && !error && taskId && !taskSucceeded && (
            <p className="report-page-note">
              该任务尚未完成或没有研报，请先完成一次产业分析。
            </p>
          )}
          {!loading && !error && !taskId && (
            <p className="report-page-note">
              未指定分析任务。请先到
              <Link to="/workbench" className="report-page-link">工作台</Link>
              提交一次政策分析，再查看完整研报。
            </p>
          )}
          {taskSucceeded && !report && (
            <p className="report-page-note">该任务未生成研报。</p>
          )}
          {report && (
            <>
              <div className="report-page-head">
                <h2 className="section-title">产业研究报告</h2>
                {taskId && (
                  <a className="report-link" href={reportUrl(taskId)} download>
                    下载 Markdown 简报
                  </a>
                )}
              </div>
              <ReportBlock report={report} />
            </>
          )}
        </div>
      </main>
    </div>
  );
}
