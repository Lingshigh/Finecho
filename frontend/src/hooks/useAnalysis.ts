import { useCallback, useEffect, useReducer, useRef } from "react";
import type { AnalysisRequest, AnalysisTask, Phase, SseEvent } from "../types/api";
import { apiUrl, fetchTask, submitAnalysis } from "../lib/http";
import { STEP_LABELS } from "../lib/progress";

interface AnalysisState {
  phase: Phase;
  taskId: string | null;
  events: SseEvent[];
  task: AnalysisTask | null;
  error: string | null;
}

type Action =
  | { type: "submit" }
  | { type: "started"; taskId: string }
  | { type: "event"; event: SseEvent }
  | { type: "task"; task: AnalysisTask }
  | { type: "complete" }
  | { type: "failed"; message: string }
  | { type: "reset" };

const initialState: AnalysisState = {
  phase: "idle",
  taskId: null,
  events: [],
  task: null,
  error: null,
};

function reducer(state: AnalysisState, action: Action): AnalysisState {
  switch (action.type) {
    case "submit":
      return {
        ...state,
        phase: "submitting",
        taskId: null,
        task: null,
        events: [],
        error: null,
      };
    case "started":
      return {
        ...state,
        phase: "running",
        taskId: action.taskId,
        task: null,
        events: [],
        error: null,
      };
    case "event": {
      // 幂等去重：同一事件只 append 一次（EventSource 重连可能重放）。
      const duplicate = state.events.some(
        (e) => e.type === action.event.type && e.at === action.event.at
      );
      const events = duplicate ? state.events : [...state.events, action.event];
      return { ...state, events };
    }
    case "task":
      return { ...state, task: action.task };
    case "complete":
      return { ...state, phase: "complete" };
    case "failed":
      return { ...state, phase: "failed", error: action.message };
    case "reset":
      return initialState;
    default:
      return state;
  }
}

const POLL_FALLBACK_THRESHOLD = 3;
const POLL_INTERVAL_MS = 1200;

const SSE_EVENT_TYPES = [
  "analysis_start",
  "analysis_complete",
  "analysis_failed",
  ...Object.keys(STEP_LABELS).flatMap((node) => [
    `node_${node}_start`,
    `node_${node}_end`,
  ]),
];

function updateTaskQuery(taskId: string | null): void {
  const url = new URL(window.location.href);
  if (taskId) url.searchParams.set("task", taskId);
  else url.searchParams.delete("task");
  window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
}

/**
 * 工作台核心状态机：提交 → SSE 实时进度 → 完成后拉任务结果。
 * SSE 连续报错超过阈值时降级为轮询 GET /analyses/{task_id}，两种来源写同一 reducer。
 */
export function useAnalysis() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const esRef = useRef<EventSource | null>(null);
  const errorCountRef = useRef(0);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const taskIdRef = useRef<string | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const startPolling = useCallback(
    (taskId: string) => {
      stopPolling();
      const poll = async () => {
        try {
          const task = await fetchTask(taskId);
          dispatch({ type: "task", task });
          if (task.status === "succeeded") {
            stopPolling();
            dispatch({ type: "complete" });
          } else if (task.status === "failed") {
            stopPolling();
            dispatch({ type: "failed", message: task.error ?? "分析失败" });
          }
        } catch {
          /* 网络抖动，下一轮重试 */
        }
      };
      pollRef.current = setInterval(poll, POLL_INTERVAL_MS);
      void poll();
    },
    [stopPolling]
  );

  const syncTerminalTask = useCallback(
    async (taskId: string) => {
      try {
        const task = await fetchTask(taskId);
        dispatch({ type: "task", task });
        if (task.status === "succeeded") {
          stopPolling();
          dispatch({ type: "complete" });
        } else {
          startPolling(taskId);
        }
      } catch {
        startPolling(taskId);
      }
    },
    [startPolling, stopPolling]
  );

  const submit = useCallback(
    async (request: AnalysisRequest) => {
      dispatch({ type: "submit" });
      taskIdRef.current = null;
      updateTaskQuery(null);
      esRef.current?.close();
      stopPolling();
      errorCountRef.current = 0;
      try {
        const accepted = await submitAnalysis(request);
        taskIdRef.current = accepted.task_id;
        dispatch({ type: "started", taskId: accepted.task_id });
        updateTaskQuery(accepted.task_id);

        const es = new EventSource(apiUrl(accepted.events_url));
        esRef.current = es;
        const handleEvent = (rawEvent: Event) => {
          const msg = rawEvent as MessageEvent<string>;
          try {
            const event = JSON.parse(msg.data) as SseEvent;
            dispatch({ type: "event", event });
            errorCountRef.current = 0;
            if (event.type === "analysis_complete") {
              es.close();
              esRef.current = null;
              void syncTerminalTask(accepted.task_id);
            }
            if (event.type === "analysis_failed") {
              es.close();
              esRef.current = null;
              dispatch({ type: "failed", message: event.detail ?? "分析失败" });
            }
          } catch {
            /* 忽略无法解析的帧 */
          }
        };
        for (const eventType of SSE_EVENT_TYPES) {
          es.addEventListener(eventType, handleEvent);
        }
        es.onerror = () => {
          errorCountRef.current += 1;
          if (errorCountRef.current >= POLL_FALLBACK_THRESHOLD) {
            es.close();
            esRef.current = null;
            if (taskIdRef.current) startPolling(taskIdRef.current);
          }
        };
      } catch (err) {
        dispatch({ type: "failed", message: err instanceof Error ? err.message : "提交失败" });
      }
    },
    [startPolling, stopPolling, syncTerminalTask]
  );

  // 从 URL 恢复（刷新后）走轮询，不重开 SSE。
  const restore = useCallback(
    (taskId: string) => {
      taskIdRef.current = taskId;
      errorCountRef.current = 0;
      dispatch({ type: "started", taskId });
      startPolling(taskId);
    },
    [startPolling]
  );

  const reset = useCallback(() => {
    esRef.current?.close();
    esRef.current = null;
    stopPolling();
    taskIdRef.current = null;
    updateTaskQuery(null);
    dispatch({ type: "reset" });
  }, [stopPolling]);

  useEffect(() => {
    return () => {
      esRef.current?.close();
      stopPolling();
    };
  }, [stopPolling]);

  return { state, submit, restore, reset };
}
