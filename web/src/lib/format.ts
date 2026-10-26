export function fmtNum(x: number | null | undefined, digits = 2): string {
  if (x == null || !Number.isFinite(x)) return "—";
  return x.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtInt(x: number | null | undefined): string {
  if (x == null || !Number.isFinite(x)) return "—";
  return Math.round(x).toLocaleString("en-US");
}

export function fmtSigned(x: number | null | undefined, digits = 0): string {
  if (x == null || !Number.isFinite(x)) return "—";
  const s = Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return (x > 0 ? "+" : x < 0 ? "−" : "") + s;
}

export function fmtUsd(x: number | null | undefined): string {
  if (x == null || !Number.isFinite(x)) return "$—";
  if (x < 0.01) return "$" + x.toFixed(4);
  if (x < 10) return "$" + x.toFixed(3);
  return "$" + x.toFixed(2);
}

export function fmtCompact(x: number | null | undefined): string {
  if (x == null || !Number.isFinite(x)) return "—";
  const a = Math.abs(x);
  if (a >= 1e6) return (x / 1e6).toFixed(1) + "M";
  if (a >= 1e4) return (x / 1e3).toFixed(1) + "k";
  if (a >= 100) return x.toFixed(0);
  if (a >= 10) return x.toFixed(1);
  return x.toFixed(2);
}

/** Largest index i with arr[i] <= x (or -1). arr ascending. */
export function upperIndex(arr: ArrayLike<number>, x: number): number {
  let lo = 0;
  let hi = arr.length - 1;
  if (hi < 0 || arr[0] > x) return -1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (arr[mid] <= x) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}

/** First index i with arr[i] >= x (arr.length if none). */
export function lowerIndex(arr: ArrayLike<number>, x: number): number {
  let lo = 0;
  let hi = arr.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (arr[mid] < x) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

export function niceStep(range: number, target: number): number {
  const raw = range / Math.max(1, target);
  const p = Math.pow(10, Math.floor(Math.log10(raw)));
  const m = raw / p;
  return (m < 1.5 ? 1 : m < 3.5 ? 2 : m < 7.5 ? 5 : 10) * p;
}

export function clamp(x: number, lo: number, hi: number): number {
  return x < lo ? lo : x > hi ? hi : x;
}
