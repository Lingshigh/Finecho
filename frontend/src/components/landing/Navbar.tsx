import { useState } from "react";
import { Link } from "react-router-dom";

const NAV_ITEMS: { label: string; links: { label: string; href: string }[] }[] = [
  {
    label: "模型",
    links: [
      { label: "工作流概览", href: "/workbench" },
      { label: "评测基准", href: "/#features" },
    ],
  },
  { label: "动态", links: [{ label: "优化记录", href: "/#features" }] },
  { label: "价格", links: [{ label: "演示版", href: "/#features" }] },
  { label: "中文", links: [{ label: "English", href: "/" }] },
];

export default function Navbar() {
  const [openDropdown, setOpenDropdown] = useState<string | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <header className="navbar">
      <div className="container navbar-inner">
        <Link to="/" className="navbar-logo">
          FinEcho
        </Link>

        <nav className={`navbar-nav${mobileOpen ? " open" : ""}`}>
          <Link to="/#features" className="nav-link">
            研究
          </Link>
          <Link to="/policies" className="nav-link">
            政策库
          </Link>
          <Link to="/workbench" className="nav-link">
            联系我们
          </Link>
          {NAV_ITEMS.map((item) => (
            <div
              key={item.label}
              className="nav-dropdown"
              onMouseEnter={() => setOpenDropdown(item.label)}
              onMouseLeave={() => setOpenDropdown(null)}
            >
              <button className="nav-link nav-dropdown-trigger">
                {item.label}
                <svg width="10" height="6" viewBox="0 0 10 6" aria-hidden="true">
                  <path d="M1 1l4 4 4-4" stroke="currentColor" fill="none" strokeWidth="1.5" />
                </svg>
              </button>
              {openDropdown === item.label && (
                <div className="dropdown-menu">
                  {item.links.map((link) => (
                    <Link key={link.label} to={link.href} className="dropdown-item">
                      {link.label}
                    </Link>
                  ))}
                </div>
              )}
            </div>
          ))}
          <Link to="/workbench" className="btn btn-primary navbar-cta">
            使用 FinEcho
            <svg width="10" height="6" viewBox="0 0 10 6" aria-hidden="true">
              <path d="M1 1l4 4 4-4" stroke="currentColor" fill="none" strokeWidth="1.5" />
            </svg>
          </Link>
        </nav>

        <button
          className="navbar-burger"
          onClick={() => setMobileOpen((v) => !v)}
          aria-label="打开菜单"
          aria-expanded={mobileOpen}
        >
          <span />
          <span />
          <span />
        </button>
      </div>
    </header>
  );
}
