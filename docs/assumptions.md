# ArBa implementation assumptions

- The requested runnable application remains in the workspace-root
  `ArBa Volume Planner.py` file. Its FastAPI API uses SQLite locally; the React
  frontend is maintained separately in `ArBa/frontend`.
- The built React app in `ArBa/frontend/dist` is served by FastAPI. During
  frontend development, Vite runs on port 5173 and proxies requests to the
  FastAPI server on port 8171.
- Microsoft Entra SSO is optional and disabled until the instance is
  configured. The first run creates only the global ArBa administrator.
  Self-registration and automatic account provisioning through SSO are
  disabled; administrators create users and roles through Configuration.
- Admin-created accounts need an initial password because local password
  authentication is supported alongside the optional SSO integration.
- Sales organization access is mapped to the market's configured P10 sales
  organization. Plan-account assignment remains a separate restriction for
  regular users. An ArBa administrator is additionally scoped to the Sales
  Orgs in their administrator-access list and can administer all plan accounts
  within those orgs.
- The first non-seeded user assigned to a Sales Org through Access Management
  becomes its ArBa administrator. Seed/demo users do not count toward this
  rule. Existing system administrators retain global access; Sales-Org admins
  may grant another user administrator access for any Sales Org.
- Platform-wide master-file and audit controls remain limited to
  system administrators because those resources are not yet partitioned by
  Sales Org.
- Master-data CSV/XLSX extracts are staged before processing. Customer extracts
  identify the market (or its sales organization), customer L04 code, and name.
  Product extracts identify one P10 OSKU, description, and brand per row; optional
  sub-brand and category fields support the product hierarchy. Baselines and
  promotions are planned directly at the P10 OSKU level.
- Promotion workflow labels map to stored states: Entry=`NEW`,
  Planned=`SAVED`, Approval Pending=`CHANGED`, and Approved=`APPROVED`.
  Shipment baselines sum the applicable ISO weeks, and only an APPROVER can
  approve a promotion. Reverting an approved promotion is limited to future
  promotions and returns it to Planned.
- Accounts with a recorded successful login are automatically deactivated
  after 30 days without another successful login. Newly created users receive
  an initial login timestamp so they are covered by the same inactivity rule.
- The local SQLite/file-storage implementation is suitable for development.
  Production use requires deployment-managed secrets, HTTPS, durable shared
  storage, and a database/worker topology appropriate to the organization.
