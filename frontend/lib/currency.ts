// Real-time FX: fetch live USD rates and convert any supported currency to USD.
// The backend stores every amount in USD, so the form converts before submitting.

export interface Currency {
  code: string;
  label: string;
  symbol: string;
}

// Codes supported by the open.er-api.com free endpoint (no API key required).
export const CURRENCIES: Currency[] = [
  { code: "USD", label: "US Dollar", symbol: "$" },
  { code: "EUR", label: "Euro", symbol: "€" },
  { code: "GBP", label: "British Pound", symbol: "£" },
  { code: "INR", label: "Indian Rupee", symbol: "₹" },
  { code: "JPY", label: "Japanese Yen", symbol: "¥" },
  { code: "RUB", label: "Russian Ruble", symbol: "₽" },
  { code: "AED", label: "UAE Dirham", symbol: "د.إ" },
  { code: "SGD", label: "Singapore Dollar", symbol: "S$" },
  { code: "AUD", label: "Australian Dollar", symbol: "A$" },
  { code: "CAD", label: "Canadian Dollar", symbol: "C$" },
  { code: "CNY", label: "Chinese Yuan", symbol: "¥" },
];

const RATES_URL = "https://open.er-api.com/v6/latest/USD";
const TTL_MS = 60 * 60 * 1000; // rates refresh hourly

interface RateCache {
  rates: Record<string, number>; // USD -> currency multipliers
  fetchedAt: number;
}

let cache: RateCache | null = null;
let inflight: Promise<Record<string, number>> | null = null;

/** Live USD-based rate table, cached for an hour and de-duplicated across callers. */
export async function getRates(): Promise<Record<string, number>> {
  if (cache && Date.now() - cache.fetchedAt < TTL_MS) return cache.rates;
  if (inflight) return inflight;

  inflight = (async () => {
    try {
      const res = await fetch(RATES_URL);
      if (!res.ok) throw new Error(`rates HTTP ${res.status}`);
      const body = await res.json();
      if (body?.result !== "success" || !body?.rates) {
        throw new Error("unexpected rates payload");
      }
      cache = { rates: body.rates as Record<string, number>, fetchedAt: Date.now() };
      return cache.rates;
    } finally {
      inflight = null;
    }
  })();
  return inflight;
}

/**
 * Convert `amount` in `code` to USD using live rates.
 * rates[code] is "how many `code` per 1 USD", so USD = amount / rates[code].
 */
export async function convertToUSD(amount: number, code: string): Promise<number> {
  if (code === "USD") return amount;
  const rates = await getRates();
  const rate = rates[code];
  if (!rate || rate <= 0) throw new Error(`no rate for ${code}`);
  return amount / rate;
}

export function currencySymbol(code: string): string {
  return CURRENCIES.find((c) => c.code === code)?.symbol ?? "";
}
