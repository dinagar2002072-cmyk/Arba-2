import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../../api";
import { type Bootstrap } from "../../types";
import { errorText } from "../../utils";

type PhasingProfile = {
  market_code: string;
  sales_org: string;
  customer_id: number;
  customer_name: string;
  duration_weeks: 2 | 3 | 4;
  percentages: number[];
  updated_at: string;
};

type PhasingConfiguration = {
  markets: { code: string; name: string; p10_sales_org: string }[];
  accounts: {
    market_code: string;
    sales_org: string;
    customer_id: number;
    customer_name: string;
  }[];
  profiles: PhasingProfile[];
};

function equalPercentages(duration: number): string[] {
  const base = Math.floor((100 / duration) * 100) / 100;
  return Array.from({ length: duration }, (_, index) =>
    (index === duration - 1 ? 100 - base * (duration - 1) : base).toFixed(2),
  );
}

export function PhasingConfig(props: {
  bootstrap: Bootstrap;
  flash: (message: string) => void;
  setError: (message: string) => void;
  refresh: () => void;
}) {
  const [configuration, setConfiguration] = useState<PhasingConfiguration>({
    markets: [],
    accounts: [],
    profiles: [],
  });
  const [marketCode, setMarketCode] = useState("");
  const [customerId, setCustomerId] = useState(0);
  const [duration, setDuration] = useState<2 | 3 | 4>(2);
  const [percentages, setPercentages] = useState<string[]>(equalPercentages(2));
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    try {
      const result = await api<PhasingConfiguration>("/admin/phasing");
      setConfiguration(result);
      const nextMarket = result.markets[0]?.code ?? "";
      const marketAccounts = result.accounts.filter((account) =>
        account.market_code === nextMarket,
      );
      const nextCustomerId = marketAccounts[0]?.customer_id ?? 0;
      setMarketCode(nextMarket);
      setCustomerId(nextCustomerId);
      const saved = result.profiles.find((profile) =>
        profile.market_code === nextMarket
        && profile.customer_id === nextCustomerId
        && profile.duration_weeks === 2,
      );
      setPercentages(saved
        ? saved.percentages.map((value) => value.toFixed(2))
        : equalPercentages(2));
    } catch (error) {
      props.setError(errorText(error));
    }
  }, [props.setError]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const accounts = configuration.accounts.filter((account) =>
    account.market_code === marketCode,
  );
  const selectedProfile = configuration.profiles.find((profile) =>
    profile.market_code === marketCode
    && profile.customer_id === customerId
    && profile.duration_weeks === duration,
  );
  const percentageTotal = percentages.reduce((total, value) => total + (Number(value) || 0), 0);

  function selectProfile(nextMarket: string, nextCustomer: number, nextDuration: 2 | 3 | 4) {
    setMarketCode(nextMarket);
    setCustomerId(nextCustomer);
    setDuration(nextDuration);
    const saved = configuration.profiles.find((profile) =>
      profile.market_code === nextMarket
      && profile.customer_id === nextCustomer
      && profile.duration_weeks === nextDuration,
    );
    setPercentages(saved
      ? saved.percentages.map((value) => value.toFixed(2))
      : equalPercentages(nextDuration));
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    try {
      const result = await api<{ profile: PhasingProfile }>("/admin/phasing", {
        method: "PUT",
        body: JSON.stringify({
          market_code: marketCode,
          customer_id: customerId,
          duration_weeks: duration,
          percentages: percentages.map(Number),
        }),
      });
      setConfiguration((current) => ({
        ...current,
        profiles: [
          ...current.profiles.filter((profile) =>
            !(profile.market_code === result.profile.market_code
              && profile.customer_id === result.profile.customer_id
              && profile.duration_weeks === result.profile.duration_weeks),
          ),
          result.profile,
        ].sort((left, right) =>
          left.market_code.localeCompare(right.market_code)
          || left.customer_name.localeCompare(right.customer_name)
          || left.duration_weeks - right.duration_weeks,
        ),
      }));
      props.flash("Promotion phasing saved.");
      props.refresh();
    } catch (error) {
      props.setError(errorText(error));
    } finally {
      setBusy(false);
    }
  }

  return <>
    <section className="panel">
      <h2>Promotion Uplift Phasing</h2>
      <p>Set how an approved promotion’s uplift is distributed across its ISO weeks. Profiles apply to every product for the selected Sales Org and Plan Account. Without a saved profile, uplift is split equally.</p>
      <form className="config-form phasing-form" onSubmit={(event) => void save(event)}>
        <label>Market / Sales Organization
          <select required value={marketCode} onChange={(event) => {
            const nextMarket = event.target.value;
            const firstAccount = configuration.accounts.find((account) =>
              account.market_code === nextMarket,
            );
            selectProfile(nextMarket, firstAccount?.customer_id ?? 0, duration);
          }}>
            {configuration.markets.map((market) => <option key={market.code} value={market.code}>
              {market.name} · {market.p10_sales_org}
            </option>)}
          </select>
        </label>
        <label>Plan Account
          <select required value={customerId} onChange={(event) =>
            selectProfile(marketCode, Number(event.target.value), duration)
          }>
            {accounts.map((account) => <option key={account.customer_id} value={account.customer_id}>
              {account.customer_name}
            </option>)}
          </select>
        </label>
        <label>Promotion Length
          <select value={duration} onChange={(event) => {
            const selectedDuration = Number(event.target.value);
            const nextDuration = selectedDuration === 3 ? 3 : selectedDuration === 4 ? 4 : 2;
            selectProfile(marketCode, customerId, nextDuration);
          }}>
            <option value={2}>2 ISO weeks</option>
            <option value={3}>3 ISO weeks</option>
            <option value={4}>4 ISO weeks</option>
          </select>
        </label>
        <div className="phasing-percentages">
          {percentages.map((value, index) => <label key={index}>
            Week {index + 1} (%)
            <input
              max="100"
              min="0"
              required
              step="0.01"
              type="number"
              value={value}
              onChange={(event) => setPercentages((current) =>
                current.map((percentage, position) =>
                  position === index ? event.target.value : percentage,
                ),
              )}
            />
          </label>)}
          <span className={Math.abs(percentageTotal - 100) <= 0.01 ? "phasing-total valid" : "phasing-total"}>
            Total: {percentageTotal.toFixed(2)}%
          </span>
        </div>
        <p className="muted small-note full-width">The number of ISO calendar weeks touched by the promotion dates selects the 2-, 3-, or 4-week profile. Percentages must total 100%. Other promotion lengths are split equally.</p>
        <button
          className="button primary"
          disabled={busy || !marketCode || !customerId || Math.abs(percentageTotal - 100) > 0.01}
          type="submit"
        >{busy ? "Saving…" : selectedProfile ? "Update Phasing" : "Save Phasing"}</button>
      </form>
    </section>
    <section className="panel">
      <h2>Saved Phasing Profiles</h2>
      <div className="table-scroll"><table className="data-table">
        <thead><tr><th>Sales Org</th><th>Plan Account</th><th>Promotion Length</th><th>Weekly Distribution</th></tr></thead>
        <tbody>
          {configuration.profiles.map((profile) => <tr key={`${profile.sales_org}-${profile.customer_id}-${profile.duration_weeks}`}>
            <td>{profile.sales_org}</td>
            <td>{profile.customer_name}</td>
            <td>{profile.duration_weeks} weeks</td>
            <td>{profile.percentages.map((percentage, index) => `Week ${index + 1}: ${percentage}%`).join(" · ")}</td>
          </tr>)}
          {!configuration.profiles.length && <tr><td className="empty-cell" colSpan={4}>No phasing profiles saved. Promotions will distribute uplift equally across their ISO weeks.</td></tr>}
        </tbody>
      </table></div>
    </section>
  </>;
}
