import { useState } from "react";
import type { GraphPayload, Verdict } from "../../types/api";
import { nodeAccent, type LayoutResult } from "../../lib/graphLayout";

interface Props {
  payload: GraphPayload;
  layout: LayoutResult;
  verdicts: Verdict[];
  loading: boolean;
  error: string | null;
}

// 公司节点按核验判定区分视觉：high_confidence 实心 / watch 描边 / hotspot_risk 虚线描边。
function verdictFor(
  nodeId: string,
  verdicts: Verdict[]
): Verdict["verdict"] | null {
  return verdicts.find((v) => v.company_id === nodeId)?.verdict ?? null;
}

export default function GraphCanvas({ payload, layout, verdicts, loading, error }: Props) {
  const [hoverId, setHoverId] = useState<string | null>(null);
  const { nodes, edges } = payload;
  const { width, height, nodeWidth, nodeHeight } = layout;

  const pos = new Map(layout.nodes.map((n) => [n.id, n]));
  const adjacent = new Set<string>();
  if (hoverId) {
    for (const edge of edges) {
      if (edge.source === hoverId || edge.target === hoverId) {
        adjacent.add(edge.source);
        adjacent.add(edge.target);
      }
    }
  }

  if (loading) {
    return <div className="graph-loading">图谱生成中…</div>;
  }
  if (error) {
    return <div className="graph-empty">图谱加载失败：{error}</div>;
  }
  if (!nodes.length) {
    return <div className="graph-empty">未匹配到上市公司，请调整政策关键词后重试。</div>;
  }

  return (
    <div className="graph-canvas">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="graph-svg"
        role="img"
        aria-label="产业链影响图谱"
      >
        <defs>
          <marker
            id="arrowhead"
            markerWidth="8"
            markerHeight="8"
            refX="7"
            refY="4"
            orient="auto"
          >
            <path d="M0 0 L8 4 L0 8 z" fill="#b9b9b4" />
          </marker>
        </defs>

        {/* 边 */}
        {edges.map((edge, i) => {
          const s = pos.get(edge.source);
          const t = pos.get(edge.target);
          if (!s || !t) return null;
          const active = hoverId != null && adjacent.has(s.id) && adjacent.has(t.id);
          const dim = hoverId != null && !active;
          const dashed = edge.relation === "benefits" && false; // 关系线型由 relation 决定
          return (
            <line
              key={`e-${i}`}
              x1={s.x + nodeWidth / 2}
              y1={s.y + nodeHeight / 2}
              x2={t.x + nodeWidth / 2}
              y2={t.y + nodeHeight / 2}
              className={`graph-edge${active ? " active" : ""}${dim ? " dim" : ""}`}
              strokeDasharray={dashed ? "6 4" : undefined}
              markerEnd={active ? "url(#arrowhead)" : undefined}
            />
          );
        })}

        {/* 节点 */}
        {layout.nodes.map((node) => {
          const active = hoverId === node.id;
          const dim = hoverId != null && !adjacent.has(node.id);
          const verdict = verdictFor(node.id, verdicts);
          return (
            <g
              key={node.id}
              className={`graph-node${active ? " active" : ""}${dim ? " dim" : ""}`}
              transform={`translate(${node.x}, ${node.y})`}
              onMouseEnter={() => setHoverId(node.id)}
              onMouseLeave={() => setHoverId(null)}
            >
              <rect
                width={nodeWidth}
                height={nodeHeight}
                rx={8}
                className={`node-rect node-${node.type}${verdict ? ` node-verdict-${verdict}` : ""}`}
                stroke={nodeAccent(node.type)}
              />
              <text
                x={nodeWidth / 2}
                y={nodeHeight / 2 + 5}
                textAnchor="middle"
                className="node-text"
              >
                {node.label.length > 12 ? `${node.label.slice(0, 12)}…` : node.label}
              </text>
            </g>
          );
        })}
      </svg>

      <div className="graph-legend">
        <span><i className="legend-dot legend-policy" />政策</span>
        <span><i className="legend-dot legend-industry" />行业</span>
        <span><i className="legend-dot legend-chain" />供应链</span>
        <span><i className="legend-dot legend-company-high" />高置信</span>
        <span><i className="legend-dot legend-company-watch" />关注</span>
        <span><i className="legend-dot legend-company-risk" />蹭热点</span>
      </div>
    </div>
  );
}
