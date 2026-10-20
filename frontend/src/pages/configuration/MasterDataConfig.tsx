import { useState } from "react";
import { api } from "../../api";
import { type Bootstrap } from "../../types";
import { encodeFile, errorText } from "../../utils";

export function MasterDataConfig(props: {
  type: "customer" | "product";
  bootstrap: Bootstrap;
  flash: (message: string) => void;
  setError: (message: string) => void;
  refresh: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [queued, setQueued] = useState<{ id: number; filename: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const customerMode = props.type === "customer";
  const title = customerMode ? "Customer Master" : "Product Master";
  const templateColumns = customerMode
    ? ["Sales Org", "Plan Account Code L04", "Plan Account Name", "Parent L03"]
    : ["P10 OSKU", "Product Description", "Brand", "Sub-brand", "Category"];
  const salesOrgs = [...new Set(props.bootstrap.markets.map((market) => market.p10_sales_org))].sort();

  function downloadTemplate() {
    const content = `${templateColumns.join(",")}\r\n`;
    const url = URL.createObjectURL(new Blob([content], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `${props.type}_master_template.csv`;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  async function upload() {
    if (!file) return props.setError("Select a CSV or XLSX extract first.");
    if (!/\.(csv|xlsx)$/i.test(file.name)) {
      return props.setError("Choose a CSV (.csv) or Excel workbook (.xlsx) file.");
    }
    setBusy(true);
    try {
      const result = await api<{ id: number; filename: string; status: string; queue_folder: string }>(
        `/admin/master-data/${props.type}/upload`,
        { method: "POST", body: JSON.stringify({ filename: file.name, content_base64: await encodeFile(file) }) },
      );
      setQueued({ id: result.id, filename: result.filename });
      props.flash(`${result.filename} is in ${result.queue_folder}.`);
      props.refresh();
    } catch (error) { props.setError(errorText(error)); }
    finally { setBusy(false); }
  }

  async function process() {
    if (!queued) return;
    setBusy(true);
    try {
      const result = await api<{ rows: number }>(`/admin/files/${queued.id}/process`, { method: "POST" });
      props.flash(`${title} loaded: ${result.rows} rows processed.`);
      setQueued(null);
      setFile(null);
      props.refresh();
    } catch (error) { props.setError(errorText(error)); }
    finally { setBusy(false); }
  }

  return <section className="panel master-panel">
    <span className="eyebrow">SAP INBOUND</span>
    <h2>Load {title} extract</h2>
    <p>Upload a CSV file (.csv) or Excel workbook (.xlsx). Files are staged in <b>Inbound Queue</b>; process performs validation and applies the entire extract atomically. Successfully processed files move to <b>Inbound Processed</b>.</p>
    <div className="required-fields">
      <b>Required columns</b>
      {customerMode ? <>
        <span><strong>Required:</strong> Sales Org, Plan Account Code L04, Plan Account Name. <strong>Optional:</strong> Parent L03.</span>
        <span>Sales Org must match a configured sales organization ({salesOrgs.length ? salesOrgs.join(", ") : "no active sales organizations are configured"}). You may use a Market Code instead, such as {props.bootstrap.markets[0]?.code ?? "a configured market code"}.</span>
        <span>Each row is one plan account (Customer L04) in one sales organization.</span>
      </> : <>
        <span><strong>Required:</strong> P10 OSKU, Product Description, Brand. <strong>Optional:</strong> Sub-brand, Category.</span>
        <span>P10 OSKU is the SAP S/4HANA material number at Product Hierarchy level 10. Use one row per OSKU; this is the planning product key shared by the baseline, listing, promotion, reporting, and feed pages. Do not upload P09-level products.</span>
      </>}
      <button className="button" onClick={downloadTemplate} type="button">Download CSV template</button>
      <span>Add data rows beneath the header before uploading. Do not rename the column headers.</span>
    </div>
    <label className="file-picker">Choose SAP extract (.csv or .xlsx)<input accept=".csv,text/csv,.xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={(event) => setFile(event.target.files?.[0] ?? null)} type="file" /></label>
    {file && <p className="selected-file">{file.name} · {(file.size / 1024).toFixed(1)} KB</p>}
    <button className="button primary" disabled={busy || !file} onClick={() => void upload()}>{busy ? "Uploading…" : "Load to Inbound Queue"}</button>
    {queued && <div className="queue-confirm"><span>{queued.filename} is queued as file #{queued.id}.</span><button className="button primary" disabled={busy} onClick={() => void process()}>Validate and consume</button></div>}
  </section>;
}
