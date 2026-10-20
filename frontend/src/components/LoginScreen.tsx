import { useState, type FormEvent } from "react";

export function LoginScreen(props: {
  busy: boolean;
  error: string;
  ssoEnabled: boolean;
  onAuthenticate: (path: "/auth/login", body: object) => Promise<void>;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const query = new URLSearchParams(window.location.search);
  const ssoError = query.get("sso_error");
  const ssoErrors: Record<string, string> = {
    cancelled: "Company SSO sign-in was cancelled.",
    authentication_failed: "Company SSO could not authenticate your account.",
    account_exists: "This email already has an ArBa account. Contact an administrator.",
    account_inactive: "This ArBa account is inactive.",
    admin_required: "Your account has not been created. Ask an ArBa administrator to create it.",
    invalid_state: "The SSO request expired. Please try again.",
  };

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void props.onAuthenticate("/auth/login", { email, password });
  }

  return (
    <main className="login-page">
      <header className="topbar"><strong className="wordmark">ArBa</strong><span className="product-title">Advanced Volume Planner</span></header>
      <section className="login-layout">
        <div className="login-copy">
          <h1>Plan with clarity.<br />Deliver with confidence.</h1>
          <p>A single workspace for baseline planning, promotions, and weekly volume visibility across your markets.</p>
        </div>
        <section className="login-card">
          <span className="eyebrow">YOUR WORKSPACE</span>
          <h2>Sign in to ArBa</h2>
          <p className="muted">Use your ArBa account or company SSO to continue.</p>
          {props.error && <p className="form-error" role="alert">{props.error}</p>}
          {ssoError && <p className="form-error" role="alert">{ssoErrors[ssoError] ?? "Company SSO could not complete sign-in."}</p>}
          {props.ssoEnabled && <button className="button sso-button" onClick={() => { window.location.href = "/api/v1/auth/sso/start"; }}>Sign in with company SSO</button>}
          <form onSubmit={submit}>
            <label htmlFor="email">Email ID</label>
            <input autoComplete="username" id="email" onChange={(event) => setEmail(event.target.value)} placeholder="name@company.com" required type="email" value={email} />
            <label htmlFor="password">Password</label>
            <input autoComplete="current-password" id="password" onChange={(event) => setPassword(event.target.value)} required type="password" value={password} />
            <button className="button primary wide" disabled={props.busy} type="submit">{props.busy ? "Please wait…" : "Sign in"}</button>
          </form>
          {!props.ssoEnabled && <p className="muted small-note">Company SSO is not configured for this instance.</p>}
        </section>
      </section>
      <footer className="login-footer"><span className="login-attribution">Designed by Dinagar Baskaran</span></footer>
    </main>
  );
}
