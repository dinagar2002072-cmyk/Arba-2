import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../../api";
import { type Bootstrap } from "../../types";
import { errorText } from "../../utils";

type ConfiguredTactic = {
  market_code: string;
  market_name: string;
  sales_org: string;
  name: string;
  incentive_type: "FIXED_LUMPSUM" | "VARIABLE";
};

type TacticConfiguration = {
  markets: { code: string; name: string; p10_sales_org: string }[];
  tactics: ConfiguredTactic[];
};

export function TacticsConfig(props: {
  bootstrap: Bootstrap;
  flash: (message: string) => void;
  setError: (message: string) => void;
  refresh: () => void;
}) {
  const [configuration, setConfiguration] = useState<TacticConfiguration>({
    markets: [],
    tactics: [],
  });
  const [marketCode, setMarketCode] = useState("");
  const [name, setName] = useState("");
  const [incentiveType, setIncentiveType] =
    useState<"FIXED_LUMPSUM" | "VARIABLE">("FIXED_LUMPSUM");
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    try {
      const result = await api<TacticConfiguration>("/admin/tactics");
      setConfiguration(result);
      setMarketCode((current) =>
        result.markets.some((market) => market.code === current)
          ? current
          : result.markets[0]?.code ?? "",
      );
    } catch (error) {
      props.setError(errorText(error));
    }
  }, [props.setError]);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function createTactic(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    try {
      await api("/admin/tactics", {
        method: "POST",
        body: JSON.stringify({
          market_code: marketCode,
          name,
          incentive_type: incentiveType,
        }),
      });
      setName("");
      props.flash("Tactic added for the selected market.");
      await reload();
      props.refresh();
    } catch (error) {
      props.setError(errorText(error));
    } finally {
      setBusy(false);
    }
  }

  const marketNames = new Map(configuration.markets.map((market) => [
    market.code,
    { name: market.name, salesOrg: market.p10_sales_org },
  ]));

  return <>
    <section className="panel">
      <h2>Create Tactic</h2>
      <p>Tactics are configured per market and sales organization. Only tactics added here can be selected on a promotion.</p>
      <form className="config-form tactic-form" onSubmit={(event) => void createTactic(event)}>
        <label>Market / Sales Organization
          <select required value={marketCode} onChange={(event) => setMarketCode(event.target.value)}>
            {configuration.markets.map((market) => <option key={market.code} value={market.code}>
              {market.name} · {market.p10_sales_org}
            </option>)}
          </select>
        </label>
        <label>Tactic Name
          <input maxLength={60} required value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <label>Incentive Type
          <select value={incentiveType} onChange={(event) =>
            setIncentiveType(
              event.target.value === "VARIABLE" ? "VARIABLE" : "FIXED_LUMPSUM",
            )
          }>
            <option value="FIXED_LUMPSUM">Fixed Lumpsum</option>
            <option value="VARIABLE">Variable (Percentage per case)</option>
          </select>
        </label>
        {!configuration.markets.length && <span className="muted small-note">No markets are available for tactic configuration.</span>}
        <button className="button primary" disabled={busy || !marketCode} type="submit">
          {busy ? "Adding…" : "Add Tactic"}
        </button>
      </form>
    </section>
    <section className="panel">
      <h2>Tactics by Market / Sales Organization</h2>
      <div className="table-scroll"><table className="data-table">
        <thead><tr><th>Market</th><th>Sales Org</th><th>Tactic</th><th>Incentive Type</th></tr></thead>
        <tbody>
          {configuration.tactics.map((tactic) => {
            const market = marketNames.get(tactic.market_code);
            return <tr key={`${tactic.market_code}-${tactic.name}`}>
              <td>{market?.name ?? tactic.market_code}</td>
              <td>{market?.salesOrg ?? "—"}</td>
              <td>{tactic.name}</td>
              <td>{tactic.incentive_type === "FIXED_LUMPSUM" ? "Fixed Lumpsum" : "Variable (Percentage per case)"}</td>
            </tr>;
          })}
          {!configuration.tactics.length && <tr><td className="empty-cell" colSpan={4}>No tactics have been configured.</td></tr>}
        </tbody>
      </table></div>
    </section>
  </>;
}
