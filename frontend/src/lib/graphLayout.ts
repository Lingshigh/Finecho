import type { GraphNode } from "../types/api";

// 由后端 nodes 的 level(0..3) 推导 SVG 图谱的节点坐标（纯函数，可单测）。
// 布局策略：按 level 分 4 列，同列节点纵向均摊，policy 在左、company 在右。

export interface LayoutNode {
  id: string;
  label: string;
  type: GraphNode["type"];
  x: number;
  y: number;
}

export interface LayoutResult {
  nodes: LayoutNode[];
  width: number;
  height: number;
  nodeWidth: number;
  nodeHeight: number;
}

export function layoutGraph(
  nodes: GraphNode[],
  opts?: { width?: number; height?: number }
): LayoutResult {
  const width = opts?.width ?? 900;
  const height = opts?.height ?? 480;
  const nodeWidth = 150;
  const nodeHeight = 44;
  const colX = (level: number) => (level / 3) * (width - nodeWidth) + 20;

  const byLevel = new Map<number, GraphNode[]>();
  for (const node of nodes) {
    const list = byLevel.get(node.level) ?? [];
    list.push(node);
    byLevel.set(node.level, list);
  }

  const positioned: LayoutNode[] = [];
  for (const [level, list] of byLevel) {
    const count = list.length;
    const gap = count > 1 ? (height - nodeHeight) / (count - 1) : 0;
    list.forEach((node, index) => {
      positioned.push({
        id: node.id,
        label: node.label,
        type: node.type,
        x: colX(level),
        y: index === 0 ? 20 : 20 + index * gap,
      });
    });
  }

  return { nodes: positioned, width, height, nodeWidth, nodeHeight };
}

export function nodeAccent(type: GraphNode["type"]): string {
  switch (type) {
    case "policy":
      return "#111111";
    case "industry":
      return "#3a3a3a";
    case "supply_chain":
      return "#8a8a86";
    case "company":
      return "#111111";
    default:
      return "#111111";
  }
}
