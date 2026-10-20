import { Fragment, useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "../api";
import { Heading } from "../components/Heading";
import { type PageProps, type Promotion } from "../types";
import { errorText, isoWeekForDate, today } from "../utils";

type ProductOption = { code: string; description: string };
type PromotionAuditChange = {
  change: string;
  user_id: string;
  time_stamp: string;
};

function PromotionDatePicker(props: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  allowClear?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [month, setMonth] = useState(() => {
    const initial = props.value || today();
    return initial.slice(0, 7);
  });
  const [yearText, monthText] = month.split("-");
  const year = Number(yearText);
  const monthIndex = Number(monthText) - 1;
  const firstDay = new Date(Date.UTC(year, monthIndex, 1));
  const firstMondayOffset = (firstDay.getUTCDay() + 6) % 7;
  const gridStart = new Date(Date.UTC(year, monthIndex, 1 - firstMondayOffset));
  const days = Array.from({ length: 42 }, (_, index) => {
    const day = new Date(gridStart);
    day.setUTCDate(gridStart.getUTCDate() + index);
    return day.toISOString().slice(0, 10);
  });
  const selectedWeek = props.value ? isoWeekForDate(props.value) : "";
  const monthLabel = new Intl.DateTimeFormat("en", {
    month: "long",
    timeZone: "UTC",
  }).format(firstDay);

  function moveMonth(offset: number) {
    const target = new Date(Date.UTC(year, monthIndex + offset, 1));
    setMonth(`${target.getUTCFullYear()}-${String(target.getUTCMonth() + 1).padStart(2, "0")}`);
  }

  return <div className="promotion-date-picker">
    <span className="promotion-date-label">{props.label}</span>
    <button
      aria-expanded={open}
      aria-label={`${props.label}: ${props.value || "Choose date"}`}
      className="promotion-date-trigger"
      onClick={() => {
        if (!open) setMonth((props.value || today()).slice(0, 7));
        setOpen((current) => !current);
      }}
      type="button"
    >
      <span>{props.value || "Choose date"}</span><span aria-hidden="true">▦</span>
    </button>
    {props.value && <small className="promotion-date-week">{selectedWeek.replace("-W", " · ISO week ")}</small>}
    {open && <div className="promotion-calendar-popover" role="dialog" aria-label={`${props.label} calendar`}>
      <div className="promotion-calendar-heading">
        <button aria-label="Previous month" className="button" onClick={() => moveMonth(-1)} type="button">‹</button>
        <strong>{monthLabel} {year}</strong>
        <button aria-label="Next month" className="button" onClick={() => moveMonth(1)} type="button">›</button>
      </div>
      <div className="promotion-calendar-grid">
        <span className="promotion-week-heading">Week</span>
        {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((weekday) =>
          <span className="promotion-weekday" key={weekday}>{weekday}</span>,
        )}
        {Array.from({ length: 6 }, (_, weekIndex) => {
          const rowDays = days.slice(weekIndex * 7, weekIndex * 7 + 7);
          const week = isoWeekForDate(rowDays[0]);
          return <Fragment key={week}>
            <span className="promotion-week-number">{week.split("-W")[1]}</span>
            {rowDays.map((day) => {
              const dayNumber = Number(day.slice(-2));
              const inMonth = day.slice(0, 7) === month;
              return <button
                aria-label={day}
                aria-pressed={props.value === day}
                className={`promotion-calendar-day${inMonth ? "" : " outside-month"}${props.value === day ? " selected" : ""}`}
                key={day}
                onClick={() => {
                  props.onChange(day);
                  setOpen(false);
                }}
                type="button"
              >{dayNumber}</button>;
            })}
          </Fragment>;
        })}
      </div>
      <div className="promotion-calendar-footer">
        {props.allowClear && props.value && <button className="text-button" onClick={() => {
          props.onChange("");
          setOpen(false);
        }} type="button">Clear date</button>}
        <span>Weeks run Monday–Sunday</span>
      </div>
    </div>}
  </div>;
}

function SearchableProductSelect(props: {
  label: string;
  options: ProductOption[];
  selected: string[];
  onChange: (selected: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const searchTerms = search.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const visibleOptions = props.options.filter((product) => {
    const searchableText = `${product.description} ${product.code}`.toLowerCase();
    return searchTerms.every((term) => searchableText.includes(term));
  });

  return <div className="searchable-product-select">
    <button
      aria-expanded={open}
      className="button product-select-trigger"
      onClick={() => setOpen((current) => !current)}
      type="button"
    >
      {props.selected.length ? `${props.selected.length} selected` : props.label}
      <span aria-hidden="true">{open ? "▲" : "▼"}</span>
    </button>
    {open && <div className="searchable-product-menu">
      <input
        aria-label={`Search ${props.label} by description, material number or product ID`}
        autoComplete="off"
        onChange={(event) => setSearch(event.target.value)}
        placeholder="Search description, material number or product ID"
        type="search"
        value={search}
      />
      <div className="searchable-product-options">
        {visibleOptions.map((product) => <label className="searchable-product-option" key={product.code}>
          <input
            checked={props.selected.includes(product.code)}
            onChange={(event) => props.onChange(event.target.checked
              ? [...props.selected, product.code]
              : props.selected.filter((code) => code !== product.code))}
            type="checkbox"
          />
          <span>{product.description}<small>P10 OSKU / Material No. / Product ID: {product.code}</small></span>
        </label>)}
        {!visibleOptions.length && <span className="muted small-note">No matching products.</span>}
      </div>
    </div>}
  </div>;
}

export function Promotions(props: PageProps) {
  const [promotions, setPromotions] = useState<Promotion[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<Promotion | null>(null);
  const [selectedProducts, setSelectedProducts] = useState<string[]>([]);
  const [productsToAddSelected, setProductsToAddSelected] = useState<string[]>([]);
  const [totals, setTotals] = useState<Record<string, number>>({});
  const [baselines, setBaselines] = useState<Record<string, number> | null>(null);
  const previousBaselines = useRef<Record<string, number> | null>(null);
  const [start, setStart] = useState(today());
  const [end, setEnd] = useState(today());
  const [consStart, setConsStart] = useState(today());
  const [consEnd, setConsEnd] = useState(today());
  const [description, setDescription] = useState("");
  const [comments, setComments] = useState("");
  const [incentiveValue, setIncentiveValue] = useState("0");
  const [tactic, setTactic] = useState("");
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [promotionAudits, setPromotionAudits] = useState<Record<number, PromotionAuditChange[]>>({});
  const [auditLoading, setAuditLoading] = useState<Set<number>>(new Set());
  const [filterStartDate, setFilterStartDate] = useState("");
  const [filterEndDate, setFilterEndDate] = useState("");
  const [filterProducts, setFilterProducts] = useState<string[]>([]);
  const [draftStartDate, setDraftStartDate] = useState("");
  const [draftEndDate, setDraftEndDate] = useState("");
  const [draftProducts, setDraftProducts] = useState<string[]>([]);
  const [showFilters, setShowFilters] = useState(false);
  const [selectedPromotions, setSelectedPromotions] = useState<Set<number>>(new Set());
  const reload = useCallback(() => {
    api<{ promotions: Promotion[] }>(`/promotions?market=${props.market}&customer_id=${props.customerId}`)
      .then((result) => setPromotions(result.promotions))
      .catch((error: unknown) => props.setError(errorText(error)));
  }, [props.market, props.customerId, props.setError]);
  useEffect(reload, [reload, props.refresh]);
  useEffect(() => {
    setSelectedPromotions(new Set());
    setPromotionAudits({});
    setAuditLoading(new Set());
    setFilterStartDate("");
    setFilterEndDate("");
    setFilterProducts([]);
    setDraftStartDate("");
    setDraftEndDate("");
    setDraftProducts([]);
    setShowFilters(false);
  }, [props.market, props.customerId]);
  function togglePromotionDetails(promotionId: number) {
    const opening = !expanded.has(promotionId);
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(promotionId)) next.delete(promotionId);
      else next.add(promotionId);
      return next;
    });
    if (!opening || promotionAudits[promotionId] || auditLoading.has(promotionId)) return;
    setAuditLoading((current) => new Set(current).add(promotionId));
    api<{ changes: PromotionAuditChange[] }>(`/promotions/${promotionId}/audit`)
      .then((result) => setPromotionAudits((current) => ({ ...current, [promotionId]: result.changes })))
      .catch((error: unknown) => props.setError(errorText(error)))
      .finally(() => setAuditLoading((current) => {
        const next = new Set(current);
        next.delete(promotionId);
        return next;
      }));
  }
  useEffect(() => {
    setBaselines(null);
    let currentRequest = true;
    api<{ baselines: Record<string, number> }>(
      `/promotions/baseline?market=${props.market}&customer_id=${props.customerId}&start_date=${start}&end_date=${end}`,
    )
      .then((result) => { if (currentRequest) setBaselines(result.baselines); })
      .catch((error: unknown) => { if (currentRequest) props.setError(errorText(error)); });
    return () => { currentRequest = false; };
  }, [props.market, props.customerId, props.setError, start, end]);
  const listed = props.bootstrap.listings.filter((item) => item.market_code === props.market && item.customer_id === props.customerId).map((item) => item.p10_osku);
  const available = props.bootstrap.products.filter((item) => listed.includes(item.code));
  const tactics = props.bootstrap.tactics.filter((item) => item.market_code === props.market);
  const selectedTactic = tactics.find((item) => item.name === tactic);
  const incentiveType = selectedTactic?.incentive_type
    ?? (editing?.tactic === tactic ? editing.incentive_type : null);
  function baselineFor(code: string): number {
    return baselines?.[code] ?? 0;
  }
  useEffect(() => {
    if (baselines === null) return;
    const previous = previousBaselines.current;
    setTotals((current) => {
      const next = { ...current };
      for (const code of selectedProducts) {
        const baseline = baselineFor(code);
        if (next[code] === undefined) next[code] = baseline;
        else if (previous?.[code] !== undefined) {
          next[code] = baseline + Math.max(0, next[code] - previous[code]);
        }
      }
      return next;
    });
    previousBaselines.current = baselines;
  }, [selectedProducts, baselines]);
  useEffect(() => {
    if (props.openPromotionId === null || !promotions.some((promo) => promo.id === props.openPromotionId)) return;
    const promotionId = props.openPromotionId;
    setExpanded((current) => new Set(current).add(promotionId));
    window.requestAnimationFrame(() => {
      document.getElementById(`promotion-${promotionId}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
    props.onPromotionOpened();
  }, [props.openPromotionId, props.onPromotionOpened, promotions]);
  function startCreate() {
    setEditing(null);
    setSelectedProducts([]);
    setProductsToAddSelected([]);
    setTotals({});
    previousBaselines.current = null;
    setStart(today());
    setEnd(today());
    setConsStart(today());
    setConsEnd(today());
    setDescription("");
    setComments("");
    setIncentiveValue("0");
    setTactic("");
    setShowCreate(true);
  }
  function startEdit(promo: Promotion) {
    setEditing(promo);
    setSelectedProducts(promo.items.map((item) => item.product));
    setProductsToAddSelected([]);
    setTotals(Object.fromEntries(promo.items.map((item) => [item.product, item.total])));
    previousBaselines.current = Object.fromEntries(promo.items.map((item) => [item.product, item.baseline]));
    setStart(promo.start_date);
    setEnd(promo.end_date);
    setConsStart(promo.cons_start);
    setConsEnd(promo.cons_end);
    setDescription(promo.description);
    setComments(promo.comments);
    setIncentiveValue(String(promo.incentive_value));
    setTactic(promo.tactic);
    setShowCreate(true);
  }
  async function savePromo(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const result = await api<{ promotion: Promotion; overlap_warnings: string[] }>("/promotions", { method: "POST", body: JSON.stringify({
        ...(editing ? { id: editing.id, version: editing.version } : {}),
        market: props.market, customer_id: props.customerId, start_date: start, end_date: end,
        cons_start: consStart, cons_end: consEnd, description, comments, tactic,
        incentive_value: Number(incentiveValue),
        items: Object.fromEntries(selectedProducts.map((code) => [code, totals[code] ?? 0])),
      }) });
      props.flash(editing ? "Promotion changes saved" : `Promotion ${result.promotion.promo_number} created in Entry status`);
      if (result.overlap_warnings.length) props.flash(`Overlapping promotion warning: ${result.overlap_warnings.join(", ")}`);
      setShowCreate(false);
      setEditing(null);
      reload();
    } catch (error) { props.setError(errorText(error)); }
  }
  async function statusAction(id: number, action: "save" | "confirm" | "approve" | "revert") {
    try {
      await api(`/promotions/${id}/${action}`, { method: "POST" });
      const messages = {
        save: "Promotion moved to Planned",
        confirm: "Promotion sent for approval",
        approve: "Promotion approved",
        revert: "Future promotion reverted to Planned for editing",
      };
      props.flash(messages[action]);
      reload();
    } catch (error) { props.setError(errorText(error)); }
  }
  const canEdit = props.user.role === "PLANNER" || props.user.role === "APPROVER" || props.user.role === "ADMIN";
  const canApprove = props.user.role === "APPROVER" || props.user.role === "ADMIN";
  const statusLabels: Record<string, string> = {
    NEW: "Entry",
    SAVED: "Planned",
    CHANGED: "Approval Pending",
    APPROVED: "Approved",
  };
  const productsToAdd = available.filter((product) => product.active !== false && !selectedProducts.includes(product.code));
  function addSelectedProducts() {
    if (!productsToAddSelected.length) return;
    setSelectedProducts((current) => [...current, ...productsToAddSelected.filter((code) => !current.includes(code))]);
    if (baselines !== null) {
      setTotals((current) => Object.fromEntries([
        ...Object.entries(current),
        ...productsToAddSelected.map((code) => [code, current[code] ?? baselineFor(code)]),
      ]));
    }
    setProductsToAddSelected([]);
  }
  const availableProductsInPromotions = [...new Map(
    promotions.flatMap((promo) => promo.items.map((item) => [item.product, item.description] as const)),
  )].sort((left, right) => left[1].localeCompare(right[1]));
  const activeFilterCount = Number(Boolean(filterStartDate))
    + Number(Boolean(filterEndDate))
    + Number(filterProducts.length > 0);
  const filteredPromotions = promotions.filter((promo) =>
    (!filterStartDate || promo.start_date >= filterStartDate)
    && (!filterEndDate || promo.end_date <= filterEndDate)
    && (!filterProducts.length || promo.items.some((item) => filterProducts.includes(item.product))),
  );
  const visiblePromotionIds = filteredPromotions.map((promo) => promo.id);
  const allVisibleSelected = visiblePromotionIds.length > 0
    && visiblePromotionIds.every((id) => selectedPromotions.has(id));

  async function copySelectedPromotions() {
    const promotionIds = visiblePromotionIds.filter((id) => selectedPromotions.has(id));
    if (!promotionIds.length) return;
    try {
      const result = await api<{ promotions: Promotion[] }>("/promotions/copy", {
        method: "POST",
        body: JSON.stringify({
          market: props.market,
          customer_id: props.customerId,
          promotion_ids: promotionIds,
        }),
      });
      setPromotions((current) => [...result.promotions, ...current]);
      setSelectedPromotions(new Set());
      props.flash(`${result.promotions.length} promotion${result.promotions.length === 1 ? "" : "s"} copied to next year in Entry status. Edit the dates and details before saving.`);
    } catch (error) {
      props.setError(errorText(error));
    }
  }
  return <>
    <Heading title="Promotions" subtitle={`Promo Count (filtered): ${filteredPromotions.length}`} actions={canEdit ? <button className="button primary" onClick={startCreate}>Create Promotion</button> : undefined} />
    {showCreate && <form className="panel form-grid" onSubmit={(event) => void savePromo(event)}>
      <div className="full-width"><h2>{editing ? `Edit ${editing.promo_number}` : "Create Promotion Entry"}</h2></div>
      <label className="full-width">Promotion Name / Description<input maxLength={50} value={description} onChange={(event) => setDescription(event.target.value)} /></label>
      <div className="promotion-dates full-width">
        <PromotionDatePicker label="Start Date" onChange={setStart} value={start} />
        <PromotionDatePicker label="End Date" onChange={setEnd} value={end} />
        <PromotionDatePicker label="Consumption Start Date" onChange={setConsStart} value={consStart} />
        <PromotionDatePicker label="Consumption End Date" onChange={setConsEnd} value={consEnd} />
      </div>
      <label>Tactic<select required value={tactic} onChange={(event) => setTactic(event.target.value)}><option value="">Select tactic</option>{tactics.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}{editing && tactic && !selectedTactic && <option value={tactic}>{tactic} (inactive — choose a configured tactic)</option>}</select>{!tactics.length && <small className="muted">No tactics are configured for this market. Ask an administrator to add one in Configuration.</small>}</label>
      {incentiveType === "FIXED_LUMPSUM" && <label>Lumpsum Amount<input required min="0" step="0.01" type="number" value={incentiveValue} onChange={(event) => setIncentiveValue(event.target.value)} /></label>}
      {incentiveType === "VARIABLE" && <label>Percentage per case (%)<input required max="100" min="0" step="0.01" type="number" value={incentiveValue} onChange={(event) => setIncentiveValue(event.target.value)} /></label>}
      <div className="product-picker full-width">
        <span className="product-picker-label">Add Listed Products (P10 OSKU)</span>
        {productsToAdd.length
          ? <SearchableProductSelect
              label="Select products"
              onChange={setProductsToAddSelected}
              options={productsToAdd}
              selected={productsToAddSelected}
            />
          : <span className="muted small-note">All listed products have been added.</span>}
        <button className="button" disabled={!productsToAddSelected.length} onClick={addSelectedProducts} type="button">Add products</button>
        {baselines === null && selectedProducts.length > 0 && <span className="muted small-note">Loading baseline values…</span>}
      </div>
      <div className="table-scroll full-width"><table className="data-table"><thead><tr><th>P10 OSKU</th><th>Baseline</th><th>Total Cases</th><th>Uplift</th><th /></tr></thead><tbody>
        {selectedProducts.map((code) => {
          const product = available.find((item) => item.code === code);
          if (!product) return null;
          const baseline = baselineFor(code);
          const total = totals[code] ?? baseline;
          return <tr key={code}>
            <td>{product.description}<small>{product.code}</small></td>
            <td>{baseline}</td>
            <td><input aria-label={`Total cases for ${product.description}`} disabled={baselines === null} min={baseline} step="1" type="number" value={total} onChange={(event) => setTotals((current) => ({ ...current, [code]: Number(event.target.value) }))} /></td>
            <td>{total - baseline}</td>
            <td><button aria-label={`Remove ${product.description}`} className="text-button" onClick={() => {
              setSelectedProducts((current) => current.filter((selected) => selected !== code));
              setTotals((current) => {
                const next = { ...current };
                delete next[code];
                return next;
              });
            }} type="button">Remove</button></td>
          </tr>;
        })}
        {!selectedProducts.length && <tr><td className="empty-cell" colSpan={5}>Choose listed products above to enter total cases.</td></tr>}
      </tbody></table></div>
      <label className="full-width">Comments<textarea maxLength={100} rows={2} value={comments} onChange={(event) => setComments(event.target.value)} /></label>
      <div className="form-actions full-width"><button className="button primary" disabled={!selectedProducts.length} type="submit">{editing ? "Save changes" : "Create Entry"}</button><button className="button" type="button" onClick={() => { setShowCreate(false); setEditing(null); }}>Cancel</button></div>
    </form>}
    <div className="promotion-filter-control">
      <button
        aria-expanded={showFilters}
        aria-haspopup="dialog"
        className="button"
        onClick={() => {
          if (!showFilters) {
            setDraftStartDate(filterStartDate);
            setDraftEndDate(filterEndDate);
            setDraftProducts(filterProducts);
          }
          setShowFilters((current) => !current);
        }}
        type="button"
      >
        Filters{activeFilterCount ? ` (${activeFilterCount})` : ""}
      </button>
      {showFilters && <form
        aria-label="Promotion filters"
        className="promotion-filter-popover"
        onSubmit={(event) => {
          event.preventDefault();
          setFilterStartDate(draftStartDate);
          setFilterEndDate(draftEndDate);
          setFilterProducts(draftProducts);
          setShowFilters(false);
        }}
        role="dialog"
      >
        <PromotionDatePicker allowClear label="Start Date" onChange={setDraftStartDate} value={draftStartDate} />
        <PromotionDatePicker allowClear label="End Date" onChange={setDraftEndDate} value={draftEndDate} />
        <div className="promotion-filter-products">
          <span>OSKU (P10)</span>
          <SearchableProductSelect
            label="Select OSKU (P10)"
            onChange={setDraftProducts}
            options={availableProductsInPromotions.map(([code, description]) => ({ code, description }))}
            selected={draftProducts}
          />
        </div>
        <div className="promotion-filter-actions">
          <button className="button" onClick={() => {
            setDraftStartDate("");
            setDraftEndDate("");
            setDraftProducts([]);
          }} type="button">Clear</button>
          <button className="button primary" type="submit">Apply Filter</button>
        </div>
      </form>}
    </div>
    {canEdit && <div className="promotion-copy-actions">
      <label><input checked={allVisibleSelected} disabled={!visiblePromotionIds.length} onChange={(event) => setSelectedPromotions((current) => {
        const next = new Set(current);
        for (const id of visiblePromotionIds) {
          if (event.target.checked) next.add(id);
          else next.delete(id);
        }
        return next;
      })} type="checkbox" /> Select all filtered promotions</label>
      <button className="button" disabled={!visiblePromotionIds.some((id) => selectedPromotions.has(id))} onClick={() => void copySelectedPromotions()}>Copy selected to next year as Entry</button>
    </div>}
    <div className="table-scroll"><table className="data-table"><thead><tr><th>Select</th><th>Promotion ID</th><th>Promo Description</th><th>Plan Account</th><th>Shipment</th><th>Tactic</th><th>Status</th><th>Baseline</th><th>Total</th><th>Uplift</th><th>Actions</th></tr></thead><tbody>
      {filteredPromotions.map((promo) => <Fragment key={promo.id}><tr id={`promotion-${promo.id}`}>
        <td><input aria-label={`Select promotion ${promo.promo_number} to copy`} checked={selectedPromotions.has(promo.id)} disabled={!canEdit} onChange={(event) => setSelectedPromotions((current) => {
          const next = new Set(current);
          if (event.target.checked) next.add(promo.id);
          else next.delete(promo.id);
          return next;
        })} type="checkbox" /></td>
        <td><button className="text-button" onClick={() => togglePromotionDetails(promo.id)}>{expanded.has(promo.id) ? "−" : "+"} {promo.promo_number}</button></td><td>{promo.description}</td><td>{promo.customer_name}</td><td>{promo.start_date} – {promo.end_date}</td><td>{promo.tactic}<small>{promo.incentive_configured ? promo.incentive_type === "FIXED_LUMPSUM" ? `Lumpsum: ${promo.incentive_value}` : `${promo.incentive_value}% per case` : "Incentive not specified"}</small></td><td><span className={`status ${promo.status}`}>{statusLabels[promo.status] ?? promo.status}</span></td><td>{promo.baseline}</td><td>{promo.total}</td><td>{promo.uplift}</td><td className="action-cell">
        {canEdit && ["NEW", "SAVED"].includes(promo.status) && <button className="button" onClick={() => startEdit(promo)}>Edit</button>}
        {canEdit && promo.status === "NEW" && <button className="button primary" onClick={() => void statusAction(promo.id, "save")}>Save</button>}
        {canEdit && promo.status === "SAVED" && <button className="button" onClick={() => void statusAction(promo.id, "confirm")}>Confirm</button>}
        {canApprove && promo.status === "CHANGED" && <button className="button primary" onClick={() => void statusAction(promo.id, "approve")}>Approve</button>}
        {["PLANNER", "APPROVER", "ADMIN"].includes(props.user.role) && promo.status === "APPROVED" && promo.start_date > today() && <button className="button" onClick={() => void statusAction(promo.id, "revert")}>Revert to edit</button>}
      </td></tr>{expanded.has(promo.id) && <>
        {promo.items.map((item) => <tr className="detail-row" key={`${promo.id}-${item.product}`}><td /><td /><td>{item.product}</td><td colSpan={2}>{item.description}</td><td colSpan={2}>Baseline {item.baseline} · Total {item.total}</td><td>{item.baseline}</td><td>{item.total}</td><td>Uplift {item.uplift}</td><td /></tr>)}
        <tr className="detail-row" key={`${promo.id}-audit`}><td colSpan={11}>
          <strong>Audit log</strong>
          {auditLoading.has(promo.id) ? <p className="muted">Loading audit history…</p>
            : <table className="data-table"><thead><tr><th>Change</th><th>User ID</th><th>Time Stamp</th></tr></thead><tbody>
              {(promotionAudits[promo.id] ?? []).map((change, index) => <tr key={`${promo.id}-audit-${index}`}><td>{change.change}</td><td>{change.user_id}</td><td>{change.time_stamp}</td></tr>)}
              {!promotionAudits[promo.id]?.length && <tr><td className="empty-cell" colSpan={3}>No audit history is available.</td></tr>}
            </tbody></table>}
        </td></tr>
      </>}</Fragment>)}
      {!filteredPromotions.length && <tr><td className="empty-cell" colSpan={11}>No promotions match the selected filters.</td></tr>}
    </tbody></table></div>
  </>;
}
