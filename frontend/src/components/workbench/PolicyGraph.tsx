import { useMemo } from "react";
import type {
  AuthorityLevel,
  PolicyDocument,
  PolicyLineage,
} from "../../types/api";

interface Props {
  lineage: PolicyLineage | null;
  selectedId: string | null;
  onSelect: (policyId: string) => void;
  loading: boolean;
}

interface PositionedPolicy extends PolicyDocument {
  x: number;
  y: number;
}

const LEVEL_COLUMN: Record<AuthorityLevel, number> = {
  central: 0,
  state_council: 0,
  ministry: 1,
  province: 2,
  city: 3,
  county: 3,
  unknown: 1,
};

const LEVEL_LABEL: Record<AuthorityLevel, string> = {
  central: "中央依据",
  state_council: "国务院",
  ministry: "部委执行",
  province: "省级落实",
  city: "市级落实",
  county: "区县落实",
  unknown: "待识别",
};

const LEVEL_COLOR: Record<AuthorityLevel, string> = {
  central: "#111827",
  state_council: "#334155",
  ministry: "#2563eb",
  province: "#0f766e",
  city: "#7c3aed",
  county: "#9333ea",
  unknown: "#94a3b8",
};

const RELATION_LABEL: Record<string, string> = {
  based_on: "依据",
  implements: "贯彻落实",
  localizes: "地方细化",
  interprets: "政策解读",
  cites: "引用",
  supersedes: "修订替代",
  repeals: "废止",
  overlaps: "范围重叠",
  conflicts_with: "可能冲突",
};

function shorten(title: string): string {
  const inner = title.match(/《([^》]+)》/)?.[1] ?? title;
  return inner.length > 17 ? `${inner.slice(0, 17)}…` : inner;
}

export default function PolicyGraph({ lineage, selectedId, onSelect, loading }: Props) {
  const nodes = useMemo<PositionedPolicy[]>(() => {
    if (!lineage) return [];
    const groups = new Map<number, PolicyDocument[]>();
    lineage.nodes.forEach((node) => {
      const column = LEVEL_COLUMN[node.authority_level];
      groups.set(column, [...(groups.get(column) ?? []), node]);
    });
    const positioned: PositionedPolicy[] = [];
    groups.forEach((items, column) => {
      items
        .sort((a, b) => (a.publish_date ?? "").localeCompare(b.publish_date ?? ""))
        .forEach((item, index) => {
          const gap = 430 / Math.max(items.length, 1);
          positioned.push({
            ...item,
            x: 125 + column * 250,
            y: 105 + gap * index + Math.min(gap / 2, 80),
          });
        });
    });
    return positioned;
  }, [lineage]);

  if (loading) return <div className="policy-graph-empty">政策脉络生成中…</div>;
  if (!lineage || nodes.length === 0) {
    return <div className="policy-graph-empty">选择一份政策查看上下位脉络</div>;
  }

  return (
    <div className="policy-graph-wrap">
      <div className="policy-layer-heads" aria-hidden="true">
        {["中央 / 国务院", "部委", "省级", "市 / 区县"].map((label) => (
          <span key={label}>{label}</span>
        ))}
      </div>
      <svg
        className="policy-lineage-svg"
        viewBox="0 0 1000 590"
        role="img"
        aria-label="中央、部委与地方政策脉络图"
      >
        <defs>
          <pattern id="policy-grid" width="24" height="24" patternUnits="userSpaceOnUse">
            <path d="M 24 0 L 0 0 0 24" className="policy-grid-line" />
          </pattern>
          <marker id="policy-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
            <path d="M0 0 L8 4 L0 8z" fill="#94a3b8" />
          </marker>
        </defs>
        <rect width="1000" height="590" fill="url(#policy-grid)" />
        {[250, 500, 750].map((x) => (
          <line key={x} x1={x} y1={0} x2={x} y2={590} className="policy-column-line" />
        ))}
        {lineage.edges.map((edge) => {
          const source = nodes.find((node) => node.id === edge.source_id);
          const target = nodes.find((node) => node.id === edge.target_id);
          if (!source || !target) return null;
          const sameColumn = source.x === target.x;
          const path = sameColumn
            ? `M ${source.x} ${source.y} C ${source.x + 90} ${source.y}, ${target.x + 90} ${target.y}, ${target.x} ${target.y}`
            : `M ${source.x} ${source.y} C ${(source.x + target.x) / 2} ${source.y}, ${(source.x + target.x) / 2} ${target.y}, ${target.x} ${target.y}`;
          return (
            <g key={`${edge.source_id}-${edge.target_id}-${edge.relation}`}>
              <path d={path} className="policy-relation-line" markerEnd="url(#policy-arrow)" />
              <text
                x={(source.x + target.x) / 2 + (sameColumn ? 72 : 0)}
                y={(source.y + target.y) / 2 - 7}
                className="policy-relation-label"
                textAnchor="middle"
              >
                {RELATION_LABEL[edge.relation] ?? edge.relation}
              </text>
            </g>
          );
        })}
        {nodes.map((node) => {
          const selected = node.id === selectedId;
          return (
            <g
              key={node.id}
              className={`policy-graph-node${selected ? " selected" : ""}`}
              transform={`translate(${node.x} ${node.y})`}
              onClick={() => onSelect(node.id)}
              tabIndex={0}
              role="button"
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") onSelect(node.id);
              }}
            >
              <title>{node.title}</title>
              {selected && <circle r="31" className="policy-node-ring" />}
              <circle
                r={selected ? 23 : 19}
                fill={LEVEL_COLOR[node.authority_level]}
                className="policy-node-dot"
              />
              <text y={38} textAnchor="middle" className="policy-node-label">
                {shorten(node.title)}
              </text>
              <text y={54} textAnchor="middle" className="policy-node-level">
                {LEVEL_LABEL[node.authority_level]}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="policy-graph-status">
        {nodes.length} 份文件 · {lineage.edges.length} 条政策关系
      </div>
    </div>
  );
}
