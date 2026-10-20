import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { hasPermission, isSystemAdmin, type User, api } from "./api";
import { LoginScreen } from "./components/LoginScreen";
import { pageNames } from "./constants";
import { PlanningPage } from "./pages/PlanningPage";
import { Configuration } from "./pages/configuration/Configuration";
import { type Bootstrap, type ConfigTab, type Page } from "./types";
import { errorText } from "./utils";

const planningScreenPermissions: [Page, string][] = [
  ["weekly", "weekly"],
  ["promotions", "promotions"],
  ["calendar", "calendar"],
  ["history", "history"],
  ["report", "report"],
  ["listing", "listing"],
];

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [bootstrap, setBootstrap] = useState<Bootstrap | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [page, setPage] = useState<Page>("weekly");
  const [configTab, setConfigTab] = useState<ConfigTab>("access");
  const [market, setMarket] = useState("");
  const [customerId, setCustomerId] = useState(0);
  const [revision, setRevision] = useState(0);
  const [calendarPromotionId, setCalendarPromotionId] = useState<number | null>(null);
  const [ssoEnabled, setSsoEnabled] = useState(false);
  const selection = useRef({ market: "", customerId: 0 });
  const accessiblePages = planningScreenPermissions
    .filter(([, screen]) => user && hasPermission(user, screen, "view"))
    .map(([pageName]) => pageName);
  const systemAdmin = user ? isSystemAdmin(user) : false;
  const canViewConfiguration = Boolean(user && hasPermission(user, "configuration", "view"));
  const canEditConfiguration = Boolean(user && hasPermission(user, "configuration", "edit"));

  useEffect(() => {
    if (!user) return;
    if (page === "configuration" && !canViewConfiguration) {
      setPage(accessiblePages[0] ?? "weekly");
    } else if (page !== "configuration" && !accessiblePages.includes(page)) {
      setPage(accessiblePages[0] ?? (canViewConfiguration ? "configuration" : "weekly"));
    }
  }, [accessiblePages.join("|"), canViewConfiguration, page, user]);

  useEffect(() => {
    selection.current = { market, customerId };
  }, [market, customerId]);

  const reloadBootstrap = useCallback(async () => {
    const data = await api<Bootstrap & { user: User }>("/bootstrap");
    setBootstrap(data);
    if (data.markets.length) {
      const current = selection.current;
      const selectedMarket = data.markets.some((item) => item.code === current.market)
        ? current.market
        : data.customers[0]?.market_code ?? data.markets[0].code;
      setMarket(selectedMarket);
      setCustomerId(data.customers.find((item) =>
        item.market_code === selectedMarket && item.id === current.customerId,
      )?.id ?? data.customers.find((item) => item.market_code === selectedMarket)?.id ?? 0);
    } else {
      setMarket("");
      setCustomerId(0);
    }
  }, []);
  const refresh = useCallback(() => {
    setRevision((value) => value + 1);
    void reloadBootstrap().catch((reason: unknown) => setError(errorText(reason)));
  }, [reloadBootstrap]);
  const refreshConfiguration = refresh;

  const enterApp = useCallback(
    async (authenticatedUser: User) => {
      setUser(authenticatedUser);
      await reloadBootstrap();
      setError("");
    },
    [reloadBootstrap],
  );

  useEffect(() => {
    let active = true;
    Promise.all([
      api<User>("/auth/me").catch(() => null),
      api<{ enabled: boolean }>("/auth/sso/status").catch(() => ({ enabled: false })),
    ])
      .then(async ([authenticatedUser, sso]) => {
        if (!active) return;
        setSsoEnabled(sso.enabled);
        if (authenticatedUser) {
          await enterApp(authenticatedUser);
        }
      })
      .catch((reason: unknown) => {
        if (active) setError(errorText(reason));
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [enterApp]);

  useEffect(() => {
    setError("");
  }, [page, configTab]);

  const currentMarket = bootstrap?.markets.find((item) => item.code === market);
  const customers = useMemo(
    () => bootstrap?.customers.filter((item) => item.market_code === market) ?? [],
    [bootstrap?.customers, market],
  );

  async function authenticate(path: "/auth/login", body: object) {
    setBusy(true);
    setError("");
    try {
      const result = await api<{ user: User }>(path, {
        method: "POST",
        body: JSON.stringify(body),
      });
      await enterApp(result.user);
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }

  async function signOut() {
    try {
      await api("/auth/logout", { method: "POST" });
    } finally {
      setUser(null);
      setBootstrap(null);
      setPage("weekly");
      setConfigTab("access");
      setNotice("");
    }
  }

  function flash(message: string) {
    setNotice(message);
    window.setTimeout(() => setNotice(""), 4500);
  }

  if (!user) {
    return (
      <LoginScreen
        busy={busy}
        error={error}
        ssoEnabled={ssoEnabled}
        onAuthenticate={authenticate}
      />
    );
  }
  if (!bootstrap) {
    return <main className="center-state">Loading your ArBa workspace…</main>;
  }
  const visibleProducts = bootstrap.products;
  if (!canViewConfiguration && bootstrap.markets.length === 0) {
    return (
      <main className="access-pending">
        <header className="topbar"><strong className="wordmark">ArBa</strong><button className="button" onClick={signOut}>Sign out</button></header>
        <section className="pending-card">
          <span className="eyebrow">ACCESS PENDING</span>
          <h1>Your account is ready</h1>
          <p>An ArBa administrator must assign your sales organization and plan accounts before planning data is available.</p>
          <button className="button primary" onClick={() => void reloadBootstrap()}>Check access again</button>
        </section>
      </main>
    );
  }

  const planningPages = accessiblePages;
  const activePage = page;
  function navigatePlanningPage(nextPage: Page) {
    setPage(nextPage);
  }

  return (
    <div className="app-shell">
      <header className="topbar app-topbar">
        <strong className="wordmark">ArBa</strong>
        <span className="product-title">Advanced Volume Planner</span>
        <span className="topbar-spacer" />
        <span className="user-name">{user.name}</span>
        <span className="role-pill">{user.role}</span>
        <button className="button" onClick={signOut}>Sign out</button>
      </header>
      <div className="workspace">
        <aside className="sidebar">
          <p className="nav-caption">PLANNING</p>
          {planningPages.map((item) => (
            <button
              className={`nav-button ${activePage === item ? "selected" : ""}`}
              key={item}
              onClick={() => navigatePlanningPage(item)}
            >
              {pageNames[item]}
            </button>
          ))}
          {canViewConfiguration && (
            <>
              <p className="nav-caption">CONFIGURATION</p>
              <button
                className={`nav-button ${page === "configuration" ? "selected" : ""}`}
                onClick={() => setPage("configuration")}
              >
                Configuration
              </button>
            </>
          )}
        </aside>
        <main className="main-content">
          {page !== "configuration" && <section className="selection-bar">
            <label>Market<select value={market} onChange={(event) => {
              const next = event.target.value;
              setMarket(next);
              const nextCustomer = bootstrap.customers.find((item) => item.market_code === next);
              setCustomerId(nextCustomer?.id ?? 0);
            }}>
              {bootstrap.markets.map((item) => <option key={item.code} value={item.code}>{item.code} · {item.name}</option>)}
            </select></label>
            <label>Plan Account<select value={customerId} disabled={customers.length === 0} onChange={(event) => setCustomerId(Number(event.target.value))}>
              {customers.length === 0 && <option value={0}>No plan accounts available</option>}
              {customers.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select></label>
          </section>}
          {error && <div role="alert" className="alert error-alert">{error}<button aria-label="Dismiss" onClick={() => setError("")}>×</button></div>}
          {notice && <div role="status" className="alert success-alert">{notice}</div>}
          {page === "configuration" && canViewConfiguration ? (
            <Configuration
              key={configTab}
              activeTab={configTab}
              setActiveTab={setConfigTab}
              isSystemAdmin={systemAdmin}
              canManageTactics={canEditConfiguration}
              canEditConfiguration={canEditConfiguration}
              bootstrap={bootstrap}
              flash={flash}
              setError={setError}
              refresh={refreshConfiguration}
            />
          ) : page !== "configuration" && !planningPages.includes(page) ? (
            <section className="pending-card" role="status">
              <span className="eyebrow">NO SCREEN ACCESS</span>
              <h1>No planning screens are assigned to your role</h1>
              <p>Ask an ArBa administrator to grant screen access in Configuration → Role Definition.</p>
            </section>
          ) : page !== "configuration" && (!customers.some((item) => item.id === customerId) || visibleProducts.length === 0) ? (
            <section className="pending-card master-data-empty" role="status">
              <span className="eyebrow">MASTER DATA REQUIRED</span>
              <h1>
                {visibleProducts.length === 0 && !customers.some((item) => item.id === customerId)
                  ? "Customer and Product Masters are required"
                  : visibleProducts.length === 0
                    ? "Product Master is empty"
                    : "No plan account is available"}
              </h1>
              <p>
                {[
                  !customers.some((item) => item.id === customerId)
                    ? "Load Customer Master in Configuration or ask an administrator to assign plan-account access."
                    : "",
                  visibleProducts.length === 0
                    ? "Load Product Master in Configuration before using planning pages."
                    : "",
                ].filter(Boolean).join(" ")}
              </p>
              {canViewConfiguration && <button className="button primary" onClick={() => setPage("configuration")}>Open Configuration</button>}
            </section>
          ) : (
            <PlanningPage
              key={`${activePage}-${market}-${customerId}-${revision}`}
              page={activePage}
              market={market}
              customerId={customerId}
              user={user}
              bootstrap={bootstrap}
              products={visibleProducts}
              flash={flash}
              setError={setError}
              refresh={refresh}
              openPromotionId={calendarPromotionId}
              onPromotionOpened={() => setCalendarPromotionId(null)}
              onOpenPromotion={(promotionId) => {
                if (planningPages.includes("promotions")) {
                  setCalendarPromotionId(promotionId);
                  setPage("promotions");
                }
              }}
            />
          )}
        </main>
      </div>
    </div>
  );
}
