import { useMemo } from "react";

// 点阵球体 + 轨道：纯 SVG/CSS，无外部动画库。
// 球体由散射圆点构成，外圈一条倾斜椭圆轨道旋转（CSS animation），
// 表面少量彩色节点 + 连接线增加科技感。prefers-reduced-motion 下停止旋转。

interface Dot {
  x: number;
  y: number;
  r: number;
  a: number; // 透明度 0-1
}

function buildDots(count: number, radius: number, cx: number, cy: number): Dot[] {
  const dots: Dot[] = [];
  for (let i = 0; i < count; i++) {
    // 在球面上均匀分布：黄金角 + 纵向余弦分布（Fibonacci 球面点集）。
    const phi = Math.acos(1 - (2 * (i + 0.5)) / count);
    const theta = Math.PI * (1 + Math.sqrt(5)) * i;
    const x = cx + radius * Math.sin(phi) * Math.cos(theta);
    const y = cy + radius * Math.sin(phi) * Math.sin(theta);
    // 越靠边缘越淡，模拟立体感。
    const z = Math.cos(phi);
    dots.push({ x, y, r: 1 + Math.abs(z) * 1.6, a: 0.18 + Math.abs(z) * 0.55 });
  }
  return dots;
}

export default function HeroOrb() {
  const size = 480;
  const cx = size / 2;
  const cy = size / 2;
  const radius = 150;
  const dots = useMemo(() => buildDots(240, radius, cx, cy), [cx, cy, radius]);

  // 三个彩色节点（科技感点缀）。
  const accents = [
    { x: cx + 40, y: cy - 60, color: "#2563eb" },
    { x: cx - 55, y: cy + 35, color: "#ea580c" },
    { x: cx + 5, y: cy + 70, color: "#16a34a" },
  ];

  return (
    <div className="hero-orb" aria-hidden="true">
      <svg viewBox={`0 0 ${size} ${size}`} className="hero-orb-svg">
        {/* 轨道环（外层，绕球心旋转） */}
        <g className="orbital">
          <ellipse
            cx={cx}
            cy={cy}
            rx={radius + 46}
            ry={radius + 20}
            fill="none"
            stroke="#d4d4d0"
            strokeWidth="1"
            transform={`rotate(-18 ${cx} ${cy})`}
          />
          <ellipse
            cx={cx}
            cy={cy}
            rx={radius + 78}
            ry={radius + 34}
            fill="none"
            stroke="#e5e5e2"
            strokeWidth="0.8"
            transform={`rotate(-18 ${cx} ${cy})`}
            strokeDasharray="2 6"
          />
          {/* 轨道上的一颗小卫星 */}
          <circle cx={cx + radius + 46} cy={cy} r="3" fill="#111" />
        </g>

        {/* 球体点阵 */}
        {dots.map((dot, i) => (
          <circle key={i} cx={dot.x} cy={dot.y} r={dot.r} fill="#3a3a3a" opacity={dot.a} />
        ))}

        {/* 彩色节点 + 连接线 */}
        <g className="orb-accents">
          {accents.map((a, i) => (
            <g key={i}>
              <line
                x1={a.x}
                y1={a.y}
                x2={accents[(i + 1) % accents.length].x}
                y2={accents[(i + 1) % accents.length].y}
                stroke="#c9c9c4"
                strokeWidth="1"
              />
              <circle cx={a.x} cy={a.y} r="4" fill={a.color} className="orb-pulse" />
            </g>
          ))}
        </g>
      </svg>
    </div>
  );
}
