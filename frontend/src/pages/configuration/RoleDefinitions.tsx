import { useEffect, useState } from "react";
import { api } from "../../api";
import { roleActions, roleScreens } from "../../constants";
import { type RoleDefinition } from "../../types";
import { errorText } from "../../utils";

export function RoleDefinitions(props: {
  flash: (message: string) => void;
  setError: (message: string) => void;
}) {
  const [roles, setRoles] = useState<RoleDefinition[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [permissions, setPermissions] = useState<Record<string, string[]>>({});
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);

  async function loadRoles() {
    const result = await api<{ roles: RoleDefinition[] }>("/admin/roles");
    setRoles(result.roles);
    setSelectedId((current) => current && result.roles.some((role) => role.id === current)
      ? current : null);
  }

  useEffect(() => {
    loadRoles().catch((error: unknown) => props.setError(errorText(error)));
  }, [props.setError]);

  useEffect(() => {
    if (creating) return;
    const selected = roles.find((role) => role.id === selectedId);
    if (!selected) return;
    setName(selected.name);
    setPermissions(selected.permissions);
  }, [creating, roles, selectedId]);

  function togglePermission(screen: string, action: string, checked: boolean) {
    setPermissions((current) => {
      const actions = new Set(current[screen] ?? []);
      if (checked) {
        actions.add(action);
        if (action !== "view") actions.add("view");
      } else if (action === "view") {
        actions.clear();
      } else {
        actions.delete(action);
      }
      return { ...current, [screen]: [...actions] };
    });
  }

  function startCreate() {
    setCreating(true);
    setSelectedId(null);
    setName("");
    setPermissions({});
  }

  async function save() {
    if (!name.trim()) {
      props.setError("Enter a role name.");
      return;
    }
    setBusy(true);
    try {
      const path = creating ? "/admin/roles" : `/admin/roles/${selectedId}`;
      const result = await api<{ role: RoleDefinition }>(path, {
        method: creating ? "POST" : "PUT",
        body: JSON.stringify({ name, permissions }),
      });
      props.flash(`Saved role ${result.role.name}.`);
      setCreating(false);
      await loadRoles();
      setSelectedId(result.role.id);
    } catch (error) {
      props.setError(errorText(error));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (selectedId === null) return;
    if (!window.confirm(`Delete role "${selected?.name}"? Users must be reassigned before deletion.`)) return;
    setBusy(true);
    try {
      await api(`/admin/roles/${selectedId}`, { method: "DELETE" });
      props.flash("Custom role deleted.");
      setCreating(false);
      await loadRoles();
    } catch (error) {
      props.setError(errorText(error));
    } finally {
      setBusy(false);
    }
  }

  const selected = roles.find((role) => role.id === selectedId);
  return <section className="config-section">
    <div className="panel">
      <div className="panel-heading">
        <div><h2>Role Definition</h2><p>Create roles and control which screens they can access and what actions they can perform. The system Admin role is fixed.</p></div>
        <button className="button" disabled={busy} onClick={startCreate} type="button">Create role</button>
      </div>
      <h3>Role</h3>
      {!roles.length
        ? <p className="muted">Loading role definitions…</p>
        : <div className="table-scroll">
            <table className="data-table role-list-table">
              <thead><tr><th>Role Name</th><th>Actions</th></tr></thead>
              <tbody>{roles.map((role) => <tr key={role.id}>
                <td>{role.name}{role.system_key === "ADMIN" ? " (fixed)" : role.is_system ? " (built-in)" : ""}</td>
                <td><button className="button" onClick={() => {
                  setCreating(false);
                  setSelectedId(role.id);
                }} type="button">View</button></td>
              </tr>)}</tbody>
            </table>
          </div>}
      {(creating || selected) && <div className="role-definition-editor">
        <label>Role name<input disabled={Boolean(selected?.is_system)} maxLength={40} onChange={(event) => setName(event.target.value)} value={name} /></label>
        {selected?.system_key === "ADMIN"
          ? <p className="muted">System Admin always has full access and cannot be changed.</p>
          : <>
            <div className="table-scroll">
              <table className="data-table role-permission-table">
                <thead><tr><th>Screen</th>{roleActions.map((action) => <th key={action.id}>{action.label}</th>)}</tr></thead>
                <tbody>{roleScreens.map((screen) => <tr key={screen.id}>
                  <td>{screen.label}</td>
                  {roleActions.map((action) => <td key={action.id}>
                    {screen.actions.some((allowedAction) => allowedAction === action.id) && <input
                      aria-label={`${action.label} ${screen.label}`}
                      checked={(permissions[screen.id] ?? []).includes(action.id)}
                      onChange={(event) => togglePermission(screen.id, action.id, event.target.checked)}
                      type="checkbox"
                    />}
                  </td>)}
                </tr>)}</tbody>
              </table>
            </div>
            <div className="form-actions">
              <button className="button primary" disabled={busy || (!creating && !selected)} onClick={() => void save()} type="button">{busy ? "Saving…" : creating ? "Create role" : "Save role"}</button>
              {!creating && selected && !selected.is_system && <button className="button" disabled={busy} onClick={() => void remove()} type="button">Delete role</button>}
              {creating && <button className="button" disabled={busy} onClick={() => setCreating(false)} type="button">Cancel</button>}
            </div>
          </>}
      </div>}
    </div>
  </section>;
}
