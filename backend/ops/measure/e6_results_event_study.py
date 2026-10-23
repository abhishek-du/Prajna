"""Exploratory event study (2026-10-23): NSE results announcements vs stock returns.
Read-only, research only, no orders. Events: results_event HISTORICAL_FILING (NSE CSV
exports), one per (instrument, period) = the earliest dissemination. Prices: canon 1d
VENDOR_ADJUSTED closes up to 2026-10-21 (the E5 forward TEST window starts 2026-10-22).
Abnormal return = stock close-to-close return - Nifty 50 return."""

import json
import sys

import numpy as np
import pandas as pd

D = sys.argv[1] if len(sys.argv) > 1 else "."
LAST = pd.Timestamp("2026-10-21")
OUTLIER = 0.35                      # any |daily AR| above this in the window -> dropped
MAX_LAG_DAYS = 75                   # filing later than this after period end -> not a results day
PRE, POST = 5, 40

bars = pd.read_csv(f"{D}/bars.csv", parse_dates=["market_date"])
bars = bars[bars.close > 0]
px = bars.pivot(index="market_date", columns="instrument_key", values="close").sort_index()
vol = bars.assign(tv=bars.close * bars.volume).pivot(index="market_date",
                                                      columns="instrument_key", values="tv")
nifty = px.pop("NSE_INDEX|Nifty 50")
vol = vol.drop(columns=["NSE_INDEX|Nifty 50"], errors="ignore")
ret = px.pct_change(fill_method=None)
mret = nifty.pct_change(fill_method=None)
ar = ret.sub(mret, axis=0)
days = px.index
pos = {d: i for i, d in enumerate(days)}

ev = pd.read_csv(f"{D}/events.csv", parse_dates=["period_end"])
ev["event_at"] = pd.to_datetime(ev.event_at, utc=True).dt.tz_convert("Asia/Kolkata")
ev = ev.sort_values("event_at").groupby(["instrument_key", "period_end"], as_index=False).first()
ev["lag"] = (ev.event_at.dt.tz_localize(None).dt.normalize() - ev.period_end).dt.days
n_all = len(ev)
ev = ev[(ev.lag >= 0) & (ev.lag <= MAX_LAG_DAYS)]
n_lag = len(ev)

# day 0: the session that first trades on the news (before 15:30 IST -> that day's close,
# after -> the next session's close)
t = ev.event_at.dt.tz_localize(None)
cut = t.dt.normalize() + pd.Timedelta(hours=15, minutes=30)
d0_cal = np.where(t < cut, t.dt.normalize(), t.dt.normalize() + pd.Timedelta(days=1))
idx = np.searchsorted(days.values, d0_cal.astype("datetime64[ns]"))
ev["i0"] = idx
ev = ev[(ev.i0 >= PRE + 21) & (ev.i0 + POST < len(days)) & ev.instrument_key.isin(px.columns)]
ev["day0"] = days[ev.i0.values]

rows = []
cols = {k: j for j, k in enumerate(px.columns)}
A = ar.values
V = vol.reindex(columns=px.columns).values
for k, i0, d0, pe in zip(ev.instrument_key, ev.i0, ev.day0, ev.period_end, strict=True):
    j = cols[k]
    w = A[i0 - PRE:i0 + POST + 1, j]
    if np.isnan(w).any() or (np.abs(w) > OUTLIER).any():
        continue
    base = A[i0 - 25 - 60:i0 - 25, j] if i0 >= 90 else A[:i0 - 25, j]
    base = base[~np.isnan(base)]
    tv = np.nanmedian(V[i0 - 21:i0 - 1, j])
    rows.append({"key": k, "day0": d0, "period_end": pe, "tv_cr": tv / 1e7,
                 "pre": w[:PRE].sum(), "ar0": w[PRE], "car01": w[PRE:PRE + 2].sum(),
                 "car2_10": w[PRE + 2:PRE + 11].sum(), "car2_20": w[PRE + 2:PRE + 21].sum(),
                 "car2_40": w[PRE + 2:].sum(),
                 "abs0_ratio": abs(w[PRE]) / np.median(np.abs(base)) if len(base) > 20 and
                 np.median(np.abs(base)) > 0 else np.nan})
R = pd.DataFrame(rows)
R["q"] = R.day0.dt.to_period("Q")
R["year"] = R.day0.dt.year
liquid = R.tv_cr >= 1.0                       # median traded value >= Rs 1 crore / day


def tstat(x):
    x = pd.Series(x).dropna()
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))) if len(x) > 2 else None


def pead(df, horizon):
    """Each calendar quarter: quintiles of the day-0..1 reaction; mean CAR after (from day 2)
    per quintile; spread Q5 - Q1; t across quarters (each quarter one observation)."""
    df = df.copy()
    df["qq"] = df.groupby("q").car01.transform(
        lambda s: pd.qcut(s.rank(method="first"), 5, labels=False) + 1 if len(s) >= 25 else np.nan)
    df = df.dropna(subset=["qq"])
    m = df.groupby(["q", "qq"])[horizon].mean().unstack()
    spread = m[5] - m[1]
    return {"quarters": int(len(m)), "by_quintile_bps": (m.mean() * 1e4).round(1).to_dict(),
            "spread_bps": round(float(spread.mean() * 1e4), 1), "t": round(tstat(spread), 2),
            "positive_quarters": f"{int((spread > 0).sum())}/{len(spread)}"}


def summary(df):
    return {"events": int(len(df)), "stocks": int(df.key.nunique()),
            "pre_run_up_5d_bps": round(df.pre.mean() * 1e4, 1),
            "abs_ar0_median_pct": round(df.ar0.abs().median() * 100, 2),
            "abs_ar0_vs_normal_day_median_x": round(float(df.abs0_ratio.median()), 2),
            "share_abs_ar0_over_5pct": round(float((df.ar0.abs() > 0.05).mean()), 3),
            "mean_ar0_bps": round(df.ar0.mean() * 1e4, 1), "t_ar0": round(tstat(df.ar0), 2)}


out = {"filters": {"events_unique": n_all, "within_75d_of_period_end": n_lag,
                   "with_full_window_no_outlier": int(len(R)), "window": [-PRE, POST],
                   "last_price_day": str(LAST.date()), "outlier_abs_daily_ar": OUTLIER},
       "range": [str(R.day0.min().date()), str(R.day0.max().date())],
       "all": summary(R), "liquid_ge_1cr": summary(R[liquid]),
       "pead_all": {h: pead(R, h) for h in ("car2_10", "car2_20", "car2_40")},
       "pead_liquid": {h: pead(R[liquid], h) for h in ("car2_10", "car2_20", "car2_40")},
       "pead_liquid_by_year_car2_20_bps": {}}
for y, g in R[liquid].groupby("year"):
    p = pead(g, "car2_20") if g.q.nunique() >= 1 and len(g) > 100 else None
    if p:
        out["pead_liquid_by_year_car2_20_bps"][int(y)] = {"spread": p["spread_bps"],
                                                          "quarters": p["quarters"]}
print(json.dumps(out, indent=1, default=str))
R.to_csv(f"{D}/events_measured.csv", index=False)
