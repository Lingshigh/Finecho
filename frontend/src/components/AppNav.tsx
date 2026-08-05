import { Link, NavLink } from "react-router-dom";

const NAV_ITEMS = [
  { to: "/", label: "首页", end: true },
  { to: "/workbench", label: "产业分析", end: false },
  { to: "/policies", label: "政策库", end: false },
  { to: "/report", label: "产业研究报告", end: false },
];

export default function AppNav() {
  return (
    <header className="app-nav">
      <div className="container app-nav-inner">
        <Link to="/" className="app-nav-logo">
          FinEcho
        </Link>
        <nav className="app-nav-links">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `app-nav-link${isActive ? " active" : ""}`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </div>
    </header>
  );
}
