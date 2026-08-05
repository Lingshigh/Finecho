import { useEffect, useState } from "react";
import type { GraphPayload } from "../types/api";
import { fetchGraph } from "../lib/http";
import { layoutGraph, type LayoutResult } from "../lib/graphLayout";

/**
 * 任务完成后拉取图谱并推导 SVG 坐标。
 * @param taskId 任务 ID；为 null 或非 complete 时返回空。
 */
export function useGraph(taskId: string | null): {
  payload: GraphPayload | null;
  layout: LayoutResult | null;
  loading: boolean;
  error: string | null;
} {
  const [payload, setPayload] = useState<GraphPayload | null>(null);
  const [layout, setLayout] = useState<LayoutResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!taskId) {
      setPayload(null);
      setLayout(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchGraph(taskId)
      .then((data) => {
        if (cancelled) return;
        setPayload(data);
        setLayout(layoutGraph(data.nodes));
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "图谱加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [taskId]);

  return { payload, layout, loading, error };
}
