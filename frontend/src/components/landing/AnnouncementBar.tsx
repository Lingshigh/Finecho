import { useState } from "react";

export default function AnnouncementBar() {
  const [dismissed, setDismissed] = useState(false);
  if (dismissed) return null;

  return (
    <div className="announcement-bar">
      <span className="announcement-text">
        FinEcho 已接入 AKShare 真实财务与公告数据 · 演示环境数据仅供参考
      </span>
      <button
        className="announcement-close"
        onClick={() => setDismissed(true)}
        aria-label="关闭公告"
      >
        ×
      </button>
    </div>
  );
}
