import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent as ReactWheelEvent,
} from "react";
import type { GraphPayload, NodeType, Verdict } from "../../types/api";
import type { LayoutNode, LayoutResult } from "../../lib/graphLayout";

interface Props {
  payload: GraphPayload;
  layout: LayoutResult;
  verdicts: Verdict[];
  loading: boolean;
  error: string | null;
}

interface GestureState {
  kind: "pan" | "node";
  pointerId: number;
  lastX: number;
  lastY: number;
  nodeId?: string;
}

const TYPE_META: Record<NodeType, { label: string; color: string }> = {
  policy: { label: "政策", color: "#7c3aed" },
  industry: { label: "行业", color: "#2563eb" },
  supply_chain: { label: "供应链", color: "#94a3b8" },
  company: { label: "公司", color: "#0f766e" },
};

const VERDICT_META: Record<Verdict["verdict"], { label: string; color: string }> = {
  high_confidence: { label: "高置信受益", color: "#0f766e" },
  watch: { label: "持续关注", color: "#d97706" },
  hotspot_risk: { label: "蹭热点风险", color: "#dc2626" },
};

function verdictFor(nodeId: string, verdicts: Verdict[]): Verdict | undefined {
  return verdicts.find((item) => item.company_id === nodeId);
}

function nodeColor(node: LayoutNode, verdict?: Verdict): string {
  if (verdict) return VERDICT_META[verdict.verdict].color;
  return TYPE_META[node.type].color;
}

function relationLabel(relation: string): string {
  const labels: Record<string, string> = {
    impacts: "影响",
    transmits: "传导",
    benefits: "受益",
  };
  return labels[relation] ?? relation;
}

function formatProperty(key: string, value: unknown): string {
  if (typeof value === "number") {
    if (key.includes("probability") || key.includes("score")) {
      return Math.round(value * 100) + "%";
    }
    return String(Math.round(value * 1000) / 1000);
  }
  if (typeof value === "string" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function clampZoom(value: number): number {
  return Math.min(2.4, Math.max(0.5, value));
}

export default function GraphCanvas({ payload, layout, verdicts, loading, error }: Props) {
  const { nodes, edges } = payload;
  const [positions, setPositions] = useState<LayoutNode[]>(layout.nodes);
  const [query, setQuery] = useState("");
  const [enabled, setEnabled] = useState<Record<NodeType, boolean>>({
    policy: true,
    industry: true,
    supply_chain: true,
    company: true,
  });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const gestureRef = useRef<GestureState | null>(null);

  useEffect(() => {
    setPositions(layout.nodes);
    setZoom(1);
    setPan({ x: 0, y: 0 });
    setSelectedId((current) =>
      current && layout.nodes.some((node) => node.id === current) ? current : null
    );
  }, [layout]);

  const counts = useMemo(() => {
    const result: Record<NodeType, number> = {
      policy: 0,
      industry: 0,
      supply_chain: 0,
      company: 0,
    };
    for (const node of nodes) result[node.type] += 1;
    return result;
  }, [nodes]);

  const visibleNodes = useMemo(
    () => positions.filter((node) => enabled[node.type]),
    [enabled, positions]
  );
  const visibleIds = useMemo(
    () => new Set(visibleNodes.map((node) => node.id)),
    [visibleNodes]
  );
  const visibleEdges = useMemo(
    () => edges.filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target)),
    [edges, visibleIds]
  );

  const normalizedQuery = query.trim().toLowerCase();
  const matchedIds = useMemo(() => {
    if (!normalizedQuery) return new Set<string>();
    return new Set(
      nodes
        .filter(
          (node) =>
            node.label.toLowerCase().includes(normalizedQuery) ||
            node.id.toLowerCase().includes(normalizedQuery)
        )
        .map((node) => node.id)
    );
  }, [nodes, normalizedQuery]);

  const focusId = hoverId ?? selectedId;
  const connectedIds = useMemo(() => {
    const result = new Set<string>();
    if (!focusId) return result;
    result.add(focusId);
    for (const edge of visibleEdges) {
      if (edge.source === focusId) result.add(edge.target);
      if (edge.target === focusId) result.add(edge.source);
    }
    return result;
  }, [focusId, visibleEdges]);

  const selectedNode = nodes.find((node) => node.id === selectedId);
  const selectedVerdict = selectedId ? verdictFor(selectedId, verdicts) : undefined;
  const selectedRelations = selectedId
    ? edges.filter((edge) => edge.source === selectedId || edge.target === selectedId)
    : [];

  const toggleType = (type: NodeType) => {
    setEnabled((current) => ({ ...current, [type]: !current[type] }));
  };

  const resetView = () => {
    setPositions(layout.nodes);
    setZoom(1);
    setPan({ x: 0, y: 0 });
  };

  const beginNodeDrag = (
    event: ReactPointerEvent<SVGGElement>,
    nodeId: string
  ) => {
    event.stopPropagation();
    event.currentTarget.ownerSVGElement?.setPointerCapture(event.pointerId);
    gestureRef.current = {
      kind: "node",
      pointerId: event.pointerId,
      lastX: event.clientX,
      lastY: event.clientY,
      nodeId,
    };
  };

  const beginPan = (event: ReactPointerEvent<SVGSVGElement>) => {
    const target = event.target as Element;
    if (
      event.button !== 0 ||
      (target !== event.currentTarget && !target.classList.contains("graph-background"))
    ) {
      return;
    }
    event.currentTarget.setPointerCapture(event.pointerId);
    gestureRef.current = {
      kind: "pan",
      pointerId: event.pointerId,
      lastX: event.clientX,
      lastY: event.clientY,
    };
  };

  const moveGesture = (event: ReactPointerEvent<SVGSVGElement>) => {
    const gesture = gestureRef.current;
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    const dx = event.clientX - gesture.lastX;
    const dy = event.clientY - gesture.lastY;
    gesture.lastX = event.clientX;
    gesture.lastY = event.clientY;

    if (gesture.kind === "pan") {
      setPan((current) => ({ x: current.x + dx, y: current.y + dy }));
      return;
    }
    if (!gesture.nodeId) return;
    setPositions((current) =>
      current.map((node) =>
        node.id === gesture.nodeId
          ? { ...node, x: node.x + dx / zoom, y: node.y + dy / zoom }
          : node
      )
    );
  };

  const endGesture = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (gestureRef.current?.pointerId === event.pointerId) {
      gestureRef.current = null;
      if (event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId);
      }
    }
  };

  const handleWheel = (event: ReactWheelEvent<SVGSVGElement>) => {
    event.preventDefault();
    setZoom((current) => clampZoom(current * (event.deltaY > 0 ? 0.9 : 1.1)));
  };

  if (loading) return <div className="graph-loading">图谱生成中…</div>;
  if (error) return <div className="graph-empty">图谱加载失败：{error}</div>;
  if (!nodes.length) {
    return <div className="graph-empty">未匹配到产业链节点，请调整政策关键词后重试。</div>;
  }

  return (
    <div className="graph-explorer">
      <aside className="graph-sidebar">
        <div className="graph-panel-section">
          <span className="graph-panel-label">搜索节点</span>
          <input
            className="graph-search"
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="名称、代码或概念"
          />
          {normalizedQuery && (
            <span className="graph-search-result">{matchedIds.size} 个匹配节点</span>
          )}
        </div>

        <div className="graph-panel-section">
          <span className="graph-panel-label">节点类型</span>
          <div className="graph-type-list">
            {(Object.keys(TYPE_META) as NodeType[]).map((type) => (
              <button
                key={type}
                type="button"
                className={"graph-type-button" + (enabled[type] ? " active" : "")}
                onClick={() => toggleType(type)}
              >
                <i style={{ background: TYPE_META[type].color }} />
                <span>{TYPE_META[type].label}</span>
                <small>{counts[type]}</small>
              </button>
            ))}
          </div>
        </div>

        <div className="graph-panel-section graph-sidebar-note">
          <span className="graph-panel-label">操作提示</span>
          <p>滚轮缩放 · 拖动画布 · 拖动节点</p>
          <p>点击节点查看关系与核验信息</p>
        </div>
      </aside>

      <section className="graph-stage">
        <div className="graph-toolbar">
          <button type="button" onClick={() => setZoom((value) => clampZoom(value - 0.15))}>
            −
          </button>
          <span>{Math.round(zoom * 100)}%</span>
          <button type="button" onClick={() => setZoom((value) => clampZoom(value + 0.15))}>
            +
          </button>
          <button type="button" className="graph-fit-button" onClick={resetView}>
            适配
          </button>
        </div>

        <svg
          viewBox={"0 0 " + layout.width + " " + layout.height}
          className="graph-network"
          role="img"
          aria-label="可交互产业链关系图谱"
          onPointerDown={beginPan}
          onPointerMove={moveGesture}
          onPointerUp={endGesture}
          onPointerCancel={endGesture}
          onWheel={handleWheel}
        >
          <defs>
            <pattern id="graph-grid" width="24" height="24" patternUnits="userSpaceOnUse">
              <path d="M 24 0 L 0 0 0 24" className="graph-grid-line" />
            </pattern>
            <marker
              id="graph-arrow"
              markerWidth="7"
              markerHeight="7"
              refX="6"
              refY="3.5"
              orient="auto"
            >
              <path d="M0 0 L7 3.5 L0 7 z" className="graph-arrow" />
            </marker>
          </defs>
          <rect
            className="graph-background"
            width={layout.width}
            height={layout.height}
            fill="url(#graph-grid)"
          />
          <g transform={"translate(" + pan.x + " " + pan.y + ") scale(" + zoom + ")"}>
            {visibleEdges.map((edge, index) => {
              const source = positions.find((node) => node.id === edge.source);
              const target = positions.find((node) => node.id === edge.target);
              if (!source || !target) return null;
              const active =
                focusId != null && (edge.source === focusId || edge.target === focusId);
              const dim = focusId != null && !active;
              return (
                <line
                  key={edge.source + "-" + edge.target + "-" + index}
                  x1={source.x}
                  y1={source.y}
                  x2={target.x}
                  y2={target.y}
                  className={[
                    "graph-network-edge",
                    active && "active",
                    dim && "dim",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  style={{ strokeWidth: 0.8 + (edge.weight ?? 1) * 1.3 }}
                  markerEnd={active ? "url(#graph-arrow)" : undefined}
                />
              );
            })}

            {visibleNodes.map((node) => {
              const verdict = verdictFor(node.id, verdicts);
              const active = focusId === node.id;
              const selected = selectedId === node.id;
              const focusDim = focusId != null && !connectedIds.has(node.id);
              const searchDim = normalizedQuery.length > 0 && !matchedIds.has(node.id);
              const dim = focusDim || searchDim;
              return (
                <g
                  key={node.id}
                  className={[
                    "graph-network-node",
                    active && "active",
                    selected && "selected",
                    dim && "dim",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  transform={"translate(" + node.x + " " + node.y + ")"}
                  onPointerDown={(event) => beginNodeDrag(event, node.id)}
                  onMouseEnter={() => setHoverId(node.id)}
                  onMouseLeave={() => setHoverId(null)}
                  onClick={() => setSelectedId(node.id)}
                >
                  <title>{node.label}</title>
                  {selected && (
                    <circle
                      className="graph-selection-ring"
                      r={node.radius + 8}
                    />
                  )}
                  <circle
                    className="graph-node-circle"
                    r={node.radius}
                    fill={nodeColor(node, verdict)}
                    stroke={verdict?.verdict === "hotspot_risk" ? "#991b1b" : "#ffffff"}
                    strokeDasharray={verdict?.verdict === "hotspot_risk" ? "4 3" : undefined}
                  />
                  <text className="graph-node-label" y={node.radius + 16} textAnchor="middle">
                    {node.label.length > 11 ? node.label.slice(0, 11) + "…" : node.label}
                  </text>
                </g>
              );
            })}
          </g>
        </svg>

        <div className="graph-stage-status">
          {visibleNodes.length} 个节点 · {visibleEdges.length} 条关系
        </div>
      </section>

      <aside className="graph-inspector">
        {selectedNode ? (
          <>
            <div className="graph-inspector-head">
              <i style={{ background: nodeColor(
                positions.find((node) => node.id === selectedNode.id) ?? {
                  ...selectedNode,
                  x: 0,
                  y: 0,
                  radius: 12,
                },
                selectedVerdict
              ) }} />
              <div>
                <h3>{selectedNode.label}</h3>
                <span>{TYPE_META[selectedNode.type].label}</span>
              </div>
            </div>

            {selectedVerdict && (
              <div className="graph-verdict-summary">
                <strong style={{ color: VERDICT_META[selectedVerdict.verdict].color }}>
                  {VERDICT_META[selectedVerdict.verdict].label}
                </strong>
                <div>
                  <span>受益概率</span>
                  <b>{Math.round(selectedVerdict.benefit_probability * 100)}%</b>
                </div>
                <div>
                  <span>背离度</span>
                  <b>{Math.round(selectedVerdict.divergence_score * 100)}%</b>
                </div>
              </div>
            )}

            {Object.keys(selectedNode.properties ?? {}).length > 0 && (
              <dl className="graph-properties">
                {Object.entries(selectedNode.properties ?? {}).map(([key, value]) => (
                  <div key={key}>
                    <dt>{key.replace(/_/g, " ")}</dt>
                    <dd>{formatProperty(key, value)}</dd>
                  </div>
                ))}
              </dl>
            )}

            <div className="graph-relations">
              <div className="graph-relations-head">
                <span>相关关系</span>
                <small>{selectedRelations.length}</small>
              </div>
              {selectedRelations.length > 0 ? (
                selectedRelations.map((edge, index) => {
                  const otherId = edge.source === selectedNode.id ? edge.target : edge.source;
                  const other = nodes.find((node) => node.id === otherId);
                  if (!other) return null;
                  return (
                    <button
                      key={edge.source + edge.target + index}
                      type="button"
                      onClick={() => setSelectedId(other.id)}
                    >
                      <span>{other.label}</span>
                      <small>{relationLabel(edge.relation)} · {Math.round((edge.weight ?? 1) * 100)}%</small>
                    </button>
                  );
                })
              ) : (
                <p>当前筛选下没有关联节点。</p>
              )}
            </div>
          </>
        ) : (
          <div className="graph-inspector-empty">
            <div className="graph-inspector-orb" />
            <h3>选择一个节点</h3>
            <p>查看节点属性、关系路径与公司核验结论。</p>
          </div>
        )}
      </aside>

      <div className="graph-legend">
        {(Object.keys(TYPE_META) as NodeType[]).map((type) => (
          <span key={type}>
            <i className="legend-dot" style={{ background: TYPE_META[type].color }} />
            {TYPE_META[type].label}
          </span>
        ))}
        <span><i className="legend-ring legend-company-watch" />关注</span>
        <span><i className="legend-ring legend-company-risk" />蹭热点</span>
      </div>
    </div>
  );
}
