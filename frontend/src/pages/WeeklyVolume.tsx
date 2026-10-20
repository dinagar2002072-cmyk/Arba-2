import { Fragment, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { Heading } from "../components/Heading";
import { type BaselineData, type PageProps } from "../types";
import { downloadApiFile, encodeFile, errorText } from "../utils";
import { isoWeekThursday, quarterOptions, weekDateRange, weekLabel } from "../weekFilters";

export function WeeklyVolume(props: PageProps) {
  const [data, setData] = useState<BaselineData | null>(null);
  const [values, setValues] = useState<Record<string, number>>({});
  const [dirty, setDirty] = useState(false);
  const [selectedYear, setSelectedYear] = useState(new Date().getUTCFullYear());
  const [selectedQuarters, setSelectedQuarters] = useState<number[]>([1, 2, 3, 4]);
  const baselineFileInput = useRef<HTMLInputElement>(null);
  useEffect(() => {
    api<BaselineData>(`/baseline?market=${props.market}&customer_id=${props.customerId}`)
      .then((result) => {
        setData(result);
        if (result.weeks.length) {
          const availableYears = result.weeks.map((week) => isoWeekThursday(week).getUTCFullYear());
          const firstYear = availableYears[0];
          setSelectedYear((current) => availableYears.includes(current) ? current : firstYear);
        }
        setValues(Object.fromEntries(result.products.flatMap((product) =>
          result.weeks.map((week, index) => [`${product.code}|${week}`, product.baseline[index] ?? 0]),
        )));
      })
      .catch((error: unknown) => props.setError(errorText(error)));
  }, [props.market, props.customerId, props.refresh, props.setError]);
  if (!data) return <p className="muted">Loading weekly baseline volume…</p>;
  const products = data.products.filter((item) => props.products.some((product) => product.code === item.code));
  const weeks = data.weeks;
  const years = [...new Set(weeks.map((week) => isoWeekThursday(week).getUTCFullYear()))].sort();
  const availableQuarters = [...new Set(weeks
    .filter((week) => isoWeekThursday(week).getUTCFullYear() === selectedYear)
    .map((week) => Math.floor(isoWeekThursday(week).getUTCMonth() / 3) + 1))];
  const visibleWeeks = weeks.filter((week) => {
    const thursday = isoWeekThursday(week);
    const quarter = Math.floor(thursday.getUTCMonth() / 3) + 1;
    return thursday.getUTCFullYear() === selectedYear && selectedQuarters.includes(quarter);
  });
  async function save() {
    try {
      const cells = products.flatMap((product) =>
        product.active !== false
          ? weeks.map((week) => ({ product: product.code, week, qty_cs: values[`${product.code}|${week}`] ?? 0 }))
          : [],
      );
      const result = await api<{ saved: number }>("/baseline", { method: "PUT", body: JSON.stringify({ market: props.market, customer_id: props.customerId, cells }) });
      setDirty(false);
      props.flash(`Saved ${result.saved} baseline cells`);
    } catch (error) { props.setError(errorText(error)); }
  }
  async function uploadBaseline(file: File | undefined) {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".xlsx")) {
      props.setError("Select an XLSX baseline workbook.");
      return;
    }
    try {
      const result = await api<{ saved: number }>("/baseline/upload", {
        method: "POST",
        body: JSON.stringify({
          market: props.market,
          customer_id: props.customerId,
          filename: file.name,
          content_base64: await encodeFile(file),
        }),
      });
      setDirty(false);
      props.flash(`Loaded ${result.saved} weekly baseline values.`);
      props.refresh();
    } catch (error) { props.setError(errorText(error)); }
    finally {
      if (baselineFileInput.current) baselineFileInput.current.value = "";
    }
  }
  async function exportBaseline() {
    try {
      const query = new URLSearchParams({
        market: props.market,
        customer_id: String(props.customerId),
      });
      visibleWeeks.forEach((week) => query.append("weeks", week));
      await downloadApiFile(
        `/baseline/export?${query.toString()}`,
        `baseline_${props.market}_${props.customerId}.xlsx`,
      );
    } catch (error) { props.setError(errorText(error)); }
  }
  const canEdit = ["PLANNER", "APPROVER", "ADMIN"].includes(props.user.role);
  return <>
    <Heading title="Weekly Baseline Volume" actions={<>
      <button className="button" disabled={!visibleWeeks.length} onClick={() => void exportBaseline()}>Extract Baseline</button>
      <button className="button" onClick={() => void downloadApiFile(
        `/baseline/audit/export?market=${encodeURIComponent(props.market)}&customer_id=${props.customerId}`,
        `baseline_audit_${props.market}_${props.customerId}.xlsx`,
      ).catch((error: unknown) => props.setError(errorText(error)))}>Download Audit Log</button>
      {canEdit && <>
        <input ref={baselineFileInput} accept=".xlsx" className="visually-hidden" onChange={(event) => void uploadBaseline(event.target.files?.[0])} type="file" />
        <button className="button" onClick={() => baselineFileInput.current?.click()}>Load Baseline</button>
        <button className="button primary" disabled={!dirty} onClick={() => void save()}>Save baseline</button>
      </>}
    </>} />
    <div className="baseline-filters">
      <label>Year<select value={selectedYear} onChange={(event) => {
        const year = Number(event.target.value);
        setSelectedYear(year);
        setSelectedQuarters([...new Set(weeks
          .filter((week) => isoWeekThursday(week).getUTCFullYear() === year)
          .map((week) => Math.floor(isoWeekThursday(week).getUTCMonth() / 3) + 1))]);
      }}>{years.map((year) => <option key={year} value={year}>{year}</option>)}</select></label>
      <fieldset className="quarter-filter"><legend>Quarters</legend>{quarterOptions.filter((quarter) => availableQuarters.includes(quarter.value)).map((quarter) => <label key={quarter.value}><input checked={selectedQuarters.includes(quarter.value)} onChange={(event) => setSelectedQuarters((current) => event.target.checked ? [...current, quarter.value].sort() : current.filter((value) => value !== quarter.value))} type="checkbox" />{quarter.label}</label>)}</fieldset>
    </div>
    {visibleWeeks.length ? <div className="table-scroll"><table className="data-table wide-table"><thead><tr><th>Product (P10 OSKU)</th><th>Row</th>{visibleWeeks.map((week) => <th key={week} title={weekDateRange(week)}>{weekLabel(week)}</th>)}</tr></thead><tbody>
      {products.map((product) => <Fragment key={product.code}><tr><td className="sticky-product"><b>{product.description}</b><small>{product.brand} · {product.sub_brand} · {product.code}{product.active === false ? " · INACTIVE" : ""}</small></td><td>FORECAST</td>{visibleWeeks.map((week) => <td key={week}><input className="volume-input" disabled={!canEdit || product.active === false} min="0" step="1" type="number" value={values[`${product.code}|${week}`] ?? 0} onChange={(event) => { setValues((current) => ({ ...current, [`${product.code}|${week}`]: Number(event.target.value) })); setDirty(true); }} /></td>)}</tr><tr className="actual-row"><td className="sticky-product">{product.description}<small>{product.code}</small></td><td>ACTUAL LY</td>{visibleWeeks.map((week) => { const index = weeks.indexOf(week); return <td className="volume-value" key={week}>{product.actual_last_year[index]}</td>; })}</tr></Fragment>)}
    </tbody></table></div> : <p className="muted">Select at least one quarter with available future weeks.</p>}
  </>;
}
