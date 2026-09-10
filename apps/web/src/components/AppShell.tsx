import { NavLink, Outlet } from "react-router-dom";
import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { fetchBackendHealth, type BackendHealth } from "../lib/api";
import { useMaterialContext } from "../lib/useMaterialContext";

interface NavItem {
  path: string;
  title: string;
  icon: ReactNode;
}

/** 线性描边图标（ui-craft：真实 SVG 图标，不用 emoji），尺寸 16px，继承 currentColor。 */
const NAV_ITEMS: NavItem[] = [
  {
    path: "/database",
    title: "材料数据库",
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <ellipse cx="12" cy="5.5" rx="7.5" ry="3" />
        <path d="M4.5 5.5v13c0 1.66 3.36 3 7.5 3s7.5-1.34 7.5-3v-13" />
        <path d="M4.5 12c0 1.66 3.36 3 7.5 3s7.5-1.34 7.5-3" />
      </svg>
    ),
  },
  {
    path: "/predict",
    title: "结构预测",
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="12" cy="12" r="1.6" />
        <ellipse cx="12" cy="12" rx="9.5" ry="4" />
        <ellipse cx="12" cy="12" rx="9.5" ry="4" transform="rotate(60 12 12)" />
        <ellipse cx="12" cy="12" rx="9.5" ry="4" transform="rotate(120 12 12)" />
      </svg>
    ),
  },
  {
    path: "/landscape",
    title: "热膨胀景观",
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M3 20h18" />
        <path d="M4 16c3.5 0 4.5-9 8-9s4.5 6 8 6" />
        <circle cx="8.5" cy="10.2" r="1.2" />
        <circle cx="16.5" cy="12.6" r="1.2" />
      </svg>
    ),
  },
  {
    path: "/zte",
    title: "ZTE 复合设计",
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M12 3 3 8l9 5 9-5-9-5Z" />
        <path d="m3 13 9 5 9-5" />
      </svg>
    ),
  },
];

function useBackendHealth(): BackendHealth {
  const [health, setHealth] = useState<BackendHealth>({ online: false, version: null });
  useEffect(() => {
    let cancelled = false;
    const probe = () => {
      void fetchBackendHealth().then((next) => {
        if (!cancelled) setHealth(next);
      });
    };
    probe();
    const timer = window.setInterval(probe, 30_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);
  return health;
}

function BackendStatus() {
  const health = useBackendHealth();
  const stateClass = health.online ? "online" : "offline";
  const label = health.online
    ? health.version
      ? `后端在线 · v${health.version}`
      : "后端在线"
    : "后端未连接";
  return (
    <span className={`backend-status ${stateClass}`} role="status">
      <span className="dot" aria-hidden="true" />
      {label}
    </span>
  );
}

function MaterialContextBar() {
  const { context, setContext } = useMaterialContext();
  if (context === null) {
    return (
      <div className="material-context">
        <p className="material-context-hint">未选定材料。在材料数据库中选中材料后，它将跨工作区保持。</p>
      </div>
    );
  }
  return (
    <div className="material-context">
      <div className="material-context-inner">
        <div className="material-context-identity">
          <strong>{context.formula || context.materialKey}</strong>
          {context.materialKey ? <span>{context.materialKey}</span> : null}
          {context.classification ? (
            <span className={`classification-chip ${context.classification}`}>
              {context.classification === "nte" ? "NTE" : "PTE"}
            </span>
          ) : null}
        </div>
        <button type="button" className="context-clear" onClick={() => setContext(null)} aria-label="清除当前材料上下文">
          ✕
        </button>
      </div>
    </div>
  );
}

export default function AppShell() {
  return (
    <>
      <header className="app-header">
        <div className="site-brand">
          <a className="site-brand-mark" href="/database" aria-label="返回材料数据库">NTE</a>
          <div>
            <p className="eyebrow">Thermal Expansion Database</p>
            <h1>NTE Materials</h1>
          </div>
        </div>
        <BackendStatus />
      </header>

      <nav className="workspace-nav" aria-label="工作区导航">
        <div className="workspace-nav-inner">
          {NAV_ITEMS.map((item) => (
            <NavLink key={item.path} to={item.path}>
              {item.icon}
              {item.title}
            </NavLink>
          ))}
        </div>
      </nav>

      <MaterialContextBar />

      <main>
        <Outlet />
      </main>
    </>
  );
}
