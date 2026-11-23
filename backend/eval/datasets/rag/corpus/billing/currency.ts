// Currency helpers for the Meridian dashboard.

export const ZERO_DECIMAL = new Set(["JPY", "KRW"]);

/** Banker's rounding: halves go to the nearest even number. */
export function roundHalfEven(x: number): number {
  const r = Math.round(x);
  return Math.abs(x % 1) === 0.5 && r % 2 !== 0 ? r - 1 : r;
}

/** Converts a decimal amount to integer minor units (cents), respecting zero-decimal currencies. */
export function toMinorUnits(amount: number, currency: string): number {
  return ZERO_DECIMAL.has(currency) ? roundHalfEven(amount) : roundHalfEven(amount * 100);
}
