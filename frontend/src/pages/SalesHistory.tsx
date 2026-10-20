import { useEffect, useState } from "react";
import { api, hasPermission } from "../api";
import { Heading } from "../components/Heading";
import { type PageProps, type Product } from "../types";
import { downloadApiFile, errorText } from "../utils";
import { isoWeekThursday, quarterOptions, weekLabel } from "../weekFilters";

export function SalesHistory(props: PageProps) {
  const [data, setData] = useState<{
    weeks: string[];
    forecast_from: string;
    products: (Product & { values: number[] })[];
  } | null>(null);
  const [selectedYear, setSelectedYear] = useState(new Date().getUTCFullYear());
  const [selectedQuarters, setSelectedQuarters] = useState<number[]>([1, 2, 3, 4]);
  useEffect(() => {
    setData(null);
    api<{
      weeks: string[];
      forecast_from: string;
      products: (Product & { values: number[] })[];
    }>(`/history?market=${props.market}&customer_id=${props.customerId}`)
      .then((result) => {
        setData(result);
        const years = [...new Set(result.weeks.map((week) =>
          isoWeekThursday(week).getUTCFullYear(),
        ))];
        setSelectedYear((current) => years.includes(current)
          ? current
          : years.includes(new Date().getUTCFullYear())
            ? new Date().getUTCFullYear()
            : years[0] ?? current);
      })
      .catch((error: unknown) => props.setError(errorText(error)));
  }, [props.market, props.customerId, props.refresh, props.setError]);
  if (!data) return <p className="muted">Loading sales data…</p>;
  const years = [...new Set(data.weeks.map((week) => isoWeekThursday(week).getUTCFullYear()))].sort();
  const availableQuarters = [...new Set(data.weeks
    .filter((week) => isoWeekThursday(week).getUTCFullYear() === selectedYear)
    .map((week) => Math.floor(isoWeekThursday(week).getUTCMonth() / 3) + 1))];
  const visibleWeeks = data.weeks.filter((week) => {
    const thursday = isoWeekThursday(week);
    const quarter = Math.floor(thursday.getUTCMonth() / 3) + 1;
    return thursday.getUTCFullYear() === selectedYear
      && selectedQuarters.includes(quarter);
  });
  const products = data.products.filter((item) =>
    props.products.some((product) => product.code === item.code),
  );
  async function exportP10AreteData() {
    try {
      await downloadApiFile(
        `/history/p10-export?market=${encodeURIComponent(props.market)}&customer_id=${props.customerId}`,
        `p10_arete_${props.market}_${props.customerId}.xlsx`,
      );
    } catch (error) {
      props.setError(errorText(error));
    }
  }
  const canExport = hasPermission(props.user, "history", "export");
  return <>
    <Heading title="Sales Data" actions={canExport &&
      <button className="button" onClick={() => void exportP10AreteData()}>
        Download P10 Arete
      </button>
    } />
    <div className="baseline-filters">
      <label>Year<select value={selectedYear} onChange={(event) => {
        const year = Number(event.target.value);
        setSelectedYear(year);
        setSelectedQuarters([...new Set(data.weeks
          .filter((week) => isoWeekThursday(week).getUTCFullYear() === year)
          .map((week) => Math.floor(isoWeekThursday(week).getUTCMonth() / 3) + 1))]);
      }}>{years.map((year) => <option key={year} value={year}>{year}</option>)}</select></label>
      <fieldset className="quarter-filter"><legend>Quarters</legend>
        {quarterOptions.filter((quarter) => availableQuarters.includes(quarter.value)).map((quarter) =>
          <label key={quarter.value}>
            <input
              checked={selectedQuarters.includes(quarter.value)}
              onChange={(event) => setSelectedQuarters((current) => event.target.checked
                ? [...current, quarter.value].sort()
                : current.filter((value) => value !== quarter.value))}
              type="checkbox"
            />
            {quarter.label}
          </label>,
        )}
      </fieldset>
    </div>
    {visibleWeeks.length
      ? <div className="table-scroll"><table className="data-table wide-table"><thead><tr>
          <th>Product (P10 OSKU)</th>
          {visibleWeeks.map((week) => <th key={week}>{weekLabel(week)}</th>)}
        </tr></thead><tbody>
          {products.map((item) => <tr key={item.code}>
            <td className="sticky-product">{item.description}<small>{item.code}</small></td>
            {visibleWeeks.map((week) => {
              const index = data.weeks.indexOf(week);
              return <td
                className={week >= data.forecast_from ? "forecast-cell" : "volume-value"}
                key={week}
              >{Math.round(item.values[index] ?? 0)}</td>;
            })}
          </tr>)}
          {!products.length && <tr><td className="empty-cell" colSpan={visibleWeeks.length + 1}>No listed products for this plan account.</td></tr>}
        </tbody></table></div>
      : <p className="muted">Select at least one quarter.</p>}
  </>;
}
