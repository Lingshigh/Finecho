import type { GraphEdge, GraphNode } from "../types/api";

export interface LayoutNode {
  id: string;
  label: string;
  type: GraphNode["type"];
  level: number;
  x: number;
  y: number;
  radius: number;
}

export interface LayoutResult {
  nodes: LayoutNode[];
  width: number;
  height: number;
}

function hashValue(value: string): number {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return Math.abs(hash >>> 0);
}

function nodeRadius(type: GraphNode["type"]): number {
  if (type === "policy") return 24;
  if (type === "industry") return 18;
  if (type === "company") return 15;
  return 12;
}

export function layoutGraph(
  nodes: GraphNode[],
  edges: GraphEdge[],
  opts?: { width?: number; height?: number }
): LayoutResult {
  const width = opts?.width ?? 980;
  const height = opts?.height ?? 640;
  const centerX = width / 2;
  const centerY = height / 2;
  const radialDistance = [0, 145, 255, 365];

  const levelGroups = new Map<number, GraphNode[]>();
  for (const node of nodes) {
    const list = levelGroups.get(node.level) ?? [];
    list.push(node);
    levelGroups.set(node.level, list);
  }

  const positioned: LayoutNode[] = [];
  for (const [level, group] of levelGroups) {
    const ordered = [...group].sort((a, b) => a.id.localeCompare(b.id));
    ordered.forEach((node, index) => {
      if (level === 0) {
        positioned.push({
          ...node,
          x: centerX,
          y: centerY,
          radius: nodeRadius(node.type),
        });
        return;
      }

      const phase = ((hashValue(node.id) % 360) / 360) * Math.PI * 2;
      const angle = phase + (index / Math.max(1, ordered.length)) * Math.PI * 2;
      const jitter = (hashValue(node.id + ":radius") % 31) - 15;
      const distance = radialDistance[level] + jitter;
      positioned.push({
        ...node,
        x: centerX + Math.cos(angle) * distance,
        y: centerY + Math.sin(angle) * distance,
        radius: nodeRadius(node.type),
      });
    });
  }

  const byId = new Map(positioned.map((node) => [node.id, node]));
  for (let iteration = 0; iteration < 180; iteration += 1) {
    const forces = new Map(positioned.map((node) => [node.id, { x: 0, y: 0 }]));

    for (let left = 0; left < positioned.length; left += 1) {
      for (let right = left + 1; right < positioned.length; right += 1) {
        const a = positioned[left];
        const b = positioned[right];
        let dx = a.x - b.x;
        let dy = a.y - b.y;
        const distanceSquared = Math.max(64, dx * dx + dy * dy);
        const distance = Math.sqrt(distanceSquared);
        if (distance === 0) {
          dx = 1;
          dy = 0;
        }
        const strength = Math.min(5, 1250 / distanceSquared);
        const fx = (dx / distance) * strength;
        const fy = (dy / distance) * strength;
        const forceA = forces.get(a.id);
        const forceB = forces.get(b.id);
        if (forceA && a.level !== 0) {
          forceA.x += fx;
          forceA.y += fy;
        }
        if (forceB && b.level !== 0) {
          forceB.x -= fx;
          forceB.y -= fy;
        }
      }
    }

    for (const edge of edges) {
      const source = byId.get(edge.source);
      const target = byId.get(edge.target);
      if (!source || !target) continue;
      const dx = target.x - source.x;
      const dy = target.y - source.y;
      const distance = Math.max(1, Math.hypot(dx, dy));
      const desired = 105 + Math.abs(target.level - source.level) * 22;
      const strength = (distance - desired) * 0.018 * (edge.weight ?? 1);
      const fx = (dx / distance) * strength;
      const fy = (dy / distance) * strength;
      const forceSource = forces.get(source.id);
      const forceTarget = forces.get(target.id);
      if (forceSource && source.level !== 0) {
        forceSource.x += fx;
        forceSource.y += fy;
      }
      if (forceTarget && target.level !== 0) {
        forceTarget.x -= fx;
        forceTarget.y -= fy;
      }
    }

    for (const node of positioned) {
      if (node.level === 0) {
        node.x = centerX;
        node.y = centerY;
        continue;
      }
      const dx = node.x - centerX;
      const dy = node.y - centerY;
      const distance = Math.max(1, Math.hypot(dx, dy));
      const targetDistance = radialDistance[node.level];
      const radialForce = (targetDistance - distance) * 0.012;
      const force = forces.get(node.id);
      if (!force) continue;
      force.x += (dx / distance) * radialForce;
      force.y += (dy / distance) * radialForce;
      node.x = Math.min(width - 36, Math.max(36, node.x + force.x * 0.82));
      node.y = Math.min(height - 36, Math.max(36, node.y + force.y * 0.82));
    }
  }

  return { nodes: positioned, width, height };
}
