import { useEffect, useState, type FormEvent } from "react";
import { api } from "../../api";
import { type AccessData, type AccountAssignment, type AdminUser, type Bootstrap } from "../../types";
import { assignmentKey, downloadApiFile, errorText } from "../../utils";

type DropdownOption = { value: string; label: string };

function MultiSelectDropdown(props: {
  label: string;
  options: DropdownOption[];
  selected: string[];
  onChange: (selected: string[]) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const selectedLabels = props.options
    .filter((option) => props.selected.includes(option.value))
    .map((option) => option.label);

  return <div className="access-multiselect">
    <span className="access-field-label">{props.label}</span>
    <button
      aria-expanded={open}
      className="access-select-trigger"
      disabled={props.disabled}
      onClick={() => setOpen((current) => !current)}
      type="button"
    >
      <span>{selectedLabels.length ? selectedLabels.join(", ") : "Select options"}</span>
      <span aria-hidden="true">{open ? "▲" : "▼"}</span>
    </button>
    {open && <div className="access-select-menu">
      {props.options.map((option) => <label className="access-select-option" key={option.value}>
        <input
          checked={props.selected.includes(option.value)}
          onChange={(event) => props.onChange(event.target.checked
            ? [...props.selected, option.value]
            : props.selected.filter((value) => value !== option.value))}
          type="checkbox"
        />
        {option.label}
      </label>)}
      {!props.options.length && <span className="muted small-note">Select a sales organization first.</span>}
    </div>}
  </div>;
}

function accountFromKey(value: string): AccountAssignment {
  const [market_code, id] = value.split("|");
  return { market_code, customer_id: Number(id) };
}

export function AccessManagement(props: {
  bootstrap: Bootstrap;
  flash: (message: string) => void;
  setError: (message: string) => void;
  isSystemAdmin: boolean;
  canEditConfiguration: boolean;
}) {
  const [data, setData] = useState<AccessData | null>(null);
  const [revision, setRevision] = useState(0);
  const [salesOrgs, setSalesOrgs] = useState<string[]>([]);
  const [assignments, setAssignments] = useState<string[]>([]);
  const [active, setActive] = useState(true);
  const [editingUser, setEditingUser] = useState<AdminUser | null>(null);
  const [editSalesOrgs, setEditSalesOrgs] = useState<string[]>([]);
  const [editAssignments, setEditAssignments] = useState<string[]>([]);
  const [editActive, setEditActive] = useState(true);
  const [creating, setCreating] = useState(false);
  const [savingUserId, setSavingUserId] = useState<number | null>(null);
  const [deletingUserId, setDeletingUserId] = useState<number | null>(null);
  const [downloadingAudit, setDownloadingAudit] = useState(false);

  useEffect(() => {
    api<AccessData>("/admin/users")
      .then(setData)
      .catch((error: unknown) => props.setError(errorText(error)));
  }, [props.setError, revision]);

  const accountOptions = props.bootstrap.customers
    .filter((customer) => {
      const salesOrg = props.bootstrap.markets
        .find((market) => market.code === customer.market_code)?.p10_sales_org;
      return salesOrg !== undefined && salesOrgs.includes(salesOrg);
    })
    .map((customer) => ({
      value: assignmentKey({ market_code: customer.market_code, customer_id: customer.id }),
      label: `${customer.name} (${props.bootstrap.markets.find((market) => market.code === customer.market_code)?.name ?? customer.market_code})`,
    }));

  function accountOptionsFor(salesOrgValues: string[]) {
    return props.bootstrap.customers
      .filter((customer) => {
        const salesOrg = props.bootstrap.markets
          .find((market) => market.code === customer.market_code)?.p10_sales_org;
        return salesOrg !== undefined && salesOrgValues.includes(salesOrg);
      })
      .map((customer) => ({
        value: assignmentKey({ market_code: customer.market_code, customer_id: customer.id }),
        label: `${customer.name} (${props.bootstrap.markets.find((market) => market.code === customer.market_code)?.name ?? customer.market_code})`,
      }));
  }

  function selectedAccountsForSalesOrgs(
    selected: string[],
    salesOrgValues: string[],
  ): string[] {
    const allowed = new Set(accountOptionsFor(salesOrgValues).map((option) => option.value));
    return selected.filter((value) => allowed.has(value));
  }

  async function createUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    if (!salesOrgs.length) {
      props.setError("Select at least one sales organization.");
      return;
    }
    const values = new FormData(form);
    const email = String(values.get("email") ?? "");
    const name = String(values.get("name") ?? "");
    const roleId = Number(values.get("role_id"));
    setCreating(true);
    try {
      const created = await api<{
        id: number;
        email: string;
        role: string;
      }>("/admin/users", {
        method: "POST",
        body: JSON.stringify({
          email,
          name,
          role_id: roleId,
          active,
          sales_org_access: salesOrgs,
          assignments: assignments.map(accountFromKey),
        }),
      });
      props.flash(`Created User ID ${created.id} · ${created.email}.`);
      form.reset();
      setSalesOrgs([]);
      setAssignments([]);
      setActive(true);
      setRevision((value) => value + 1);
    } catch (error) {
      props.setError(errorText(error));
    } finally {
      setCreating(false);
    }
  }

  function beginEdit(user: AdminUser) {
    const userAssignments = data?.assignments
      .filter((item) => item.user_id === user.id)
      .map(assignmentKey) ?? [];
    setEditingUser(user);
    setEditSalesOrgs(user.sales_org_access);
    setEditAssignments(userAssignments);
    setEditActive(user.active);
  }

  async function saveUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editingUser) return;
    const values = new FormData(event.currentTarget);
    setSavingUserId(editingUser.id);
    try {
      await api(
        `/admin/users/${editingUser.id}`,
        {
          method: "PUT",
          body: JSON.stringify({
            role_id: Number(values.get("role_id")),
            active: editActive,
            sales_org_access: editSalesOrgs,
            assignments: editAssignments.map(accountFromKey),
          }),
        },
      );
      props.flash(`Access updated for User ID ${editingUser.id}.`);
      setEditingUser(null);
      setRevision((value) => value + 1);
    } catch (error) {
      props.setError(errorText(error));
    } finally {
      setSavingUserId(null);
    }
  }

  async function deleteUser() {
    if (!editingUser || !props.canEditConfiguration) return;
    if (!window.confirm(`Delete user ${editingUser.name} (${editingUser.email})? This cannot be undone.`)) return;
    setDeletingUserId(editingUser.id);
    try {
      await api(`/admin/users/${editingUser.id}`, { method: "DELETE" });
      props.flash(`Deleted user ${editingUser.name} (${editingUser.email}).`);
      setEditingUser(null);
      setRevision((value) => value + 1);
    } catch (error) {
      props.setError(errorText(error));
    } finally {
      setDeletingUserId(null);
    }
  }

  async function downloadUserAudit() {
    setDownloadingAudit(true);
    try {
      await downloadApiFile("/admin/users/audit-export", "user_audit.xlsx");
    } catch (error) {
      props.setError(errorText(error));
    } finally {
      setDownloadingAudit(false);
    }
  }

  if (!data) return <p className="muted">Loading users…</p>;
  const roleDefinitions = data.role_definitions ?? [];
  const salesOrgOptions = data.sales_orgs.map((item) => ({
    value: item.code,
    label: `${item.name} (${item.code})`,
  }));
  const assignableRoles = roleDefinitions.filter((role) => role.base_role !== "ADMIN");
  const adminRoleId = roleDefinitions.find((role) => role.base_role === "ADMIN")?.id;

  return <section className="config-section">
    <div className="panel">
      <div className="panel-heading"><div><h2>Create User ID</h2></div></div>
      {!roleDefinitions.length && <p className="alert error-alert">Role definitions are unavailable. Restart the backend using the updated ArBa code, then reload Configuration.</p>}
      {props.canEditConfiguration && <form className="create-user-form" onSubmit={(event) => void createUser(event)}>
        <div className="create-user-identity">
          <label>Email ID<input autoComplete="email" maxLength={254} name="email" required type="email" /></label>
          <label>User Name<input maxLength={100} minLength={2} name="name" required /></label>
          <label>ArBa Role<select defaultValue={assignableRoles[0]?.id ?? ""} disabled={!assignableRoles.length} name="role_id" required><option disabled value="">Create a role first</option>{assignableRoles.map((role) => <option key={role.id} value={role.id}>{role.name}</option>)}</select></label>
        </div>
        <div className="create-user-access">
          <MultiSelectDropdown
            label="Sales Organization"
            onChange={(selected) => {
              setSalesOrgs(selected);
              setAssignments((current) => selectedAccountsForSalesOrgs(current, selected));
            }}
            options={salesOrgOptions}
            selected={salesOrgs}
          />
          <MultiSelectDropdown
            label="Plan Account Access"
            onChange={setAssignments}
            options={accountOptions}
            selected={assignments}
            disabled={!salesOrgs.length}
          />
        </div>
        <div className="create-user-submit">
          <label className="user-active-switch">
            <input checked={active} onChange={(event) => setActive(event.target.checked)} type="checkbox" />
            <span className="switch-track" aria-hidden="true"><span /></span>
            User Active
          </label>
          <button className="button primary" disabled={creating || !assignableRoles.length} type="submit">
            {creating ? "Creating…" : "Create User"}
          </button>
        </div>
      </form>}
      {!props.canEditConfiguration && <p className="muted">Your role has view-only access to Configuration.</p>}
    </div>

    <div className="panel">
      <div className="panel-heading">
        <div><h2>Users</h2><p>Inactive users are automatically deactivated after 30 days without a successful sign-in.</p></div>
        {props.isSystemAdmin && <button className="button" disabled={downloadingAudit} onClick={() => void downloadUserAudit()} type="button">{downloadingAudit ? "Preparing…" : "User Audit"}</button>}
      </div>
      <div className="table-scroll">
        <table className="data-table user-table">
          <thead><tr><th>Active/Inactive</th><th>User Name</th><th>Email Address</th><th>ArBa Role</th><th>Actions</th></tr></thead>
          <tbody>
            {data.users.map((user) => <tr key={user.id}>
              <td><span className={`status ${user.active ? "ACTIVE" : "INACTIVE"}`}>{user.active ? "Active" : "Inactive"}</span></td>
              <td>{user.name}</td>
              <td>{user.email}</td>
              <td>{user.role}</td>
              <td>{props.canEditConfiguration && <button className="button" onClick={() => beginEdit(user)} type="button">Edit access</button>}</td>
            </tr>)}
            {!data.users.length && <tr><td className="empty-cell" colSpan={5}>No users have been created.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>

    {editingUser && <div className="modal-backdrop" role="presentation">
      <section aria-labelledby="edit-user-title" aria-modal="true" className="panel create-user-modal" role="dialog">
        <div className="panel-heading">
          <div><h2 id="edit-user-title">Edit User Access</h2><p>{editingUser.name} · {editingUser.email}</p></div>
          <button aria-label="Close" className="button" onClick={() => setEditingUser(null)} type="button">Close</button>
        </div>
        <form className="edit-user-form" onSubmit={(event) => void saveUser(event)}>
          {(() => {
            const editingAdmin = (editingUser.base_role ?? editingUser.role.toUpperCase()) === "ADMIN";
            const currentRoleId = roleDefinitions.find((role) => role.id === editingUser.role_definition_id)?.id
              ?? roleDefinitions.find((role) => role.name === editingUser.role)?.id
              ?? "";
            const options = editingAdmin ? roleDefinitions : assignableRoles;
            const selectableCurrentRoleId = options.some((role) => role.id === currentRoleId) ? currentRoleId : "";
            return <label>ArBa Role<select defaultValue={selectableCurrentRoleId} disabled={editingAdmin || !roleDefinitions.length} name={editingAdmin ? undefined : "role_id"} required><option disabled value="">Select a role</option>{options.map((role) => <option key={role.id} value={role.id}>{role.name}{role.base_role === "ADMIN" ? " (fixed)" : ""}</option>)}</select>{editingAdmin && <input name="role_id" type="hidden" value={currentRoleId || adminRoleId || ""} />}</label>;
          })()}
          <MultiSelectDropdown
            label="Sales Organization"
            onChange={(selected) => {
              setEditSalesOrgs(selected);
              setEditAssignments((current) => selectedAccountsForSalesOrgs(current, selected));
            }}
            options={salesOrgOptions}
            selected={editSalesOrgs}
          />
          <MultiSelectDropdown label="Plan Account Access" onChange={setEditAssignments} options={accountOptionsFor(editSalesOrgs)} selected={editAssignments} disabled={!editSalesOrgs.length} />
          <label className="user-active-switch">
            <input checked={editActive} onChange={(event) => setEditActive(event.target.checked)} type="checkbox" />
            <span className="switch-track" aria-hidden="true"><span /></span>
            User Active
          </label>
          <div className="form-actions">
            <button className="button primary" disabled={savingUserId === editingUser.id || !roleDefinitions.length} type="submit">{savingUserId === editingUser.id ? "Saving…" : "Save User"}</button>
            {props.canEditConfiguration && (editingUser.base_role ?? editingUser.role.toUpperCase()) !== "ADMIN" && <button className="button danger" disabled={deletingUserId === editingUser.id || savingUserId === editingUser.id} onClick={() => void deleteUser()} type="button">{deletingUserId === editingUser.id ? "Deleting…" : "Delete User"}</button>}
            <button className="button" onClick={() => setEditingUser(null)} type="button">Cancel</button>
          </div>
        </form>
      </section>
    </div>}
  </section>;
}
