# Recorded fixtures

Each file here is a real response, recorded from the live site on **2026-09-07** and
**never hand-edited**. They are evidence, not samples. Refresh one with:

    webgrab record <source-id> --out tests/fixtures/<name>

Offline tests run parsers against these and catch our regressions. The opt-in
`-m network` tests assert the live sites still have the shape recorded here, and
catch the sites' changes. Both matter; only the first runs by default.

| File | Source | Why it is kept |
|---|---|---|
| `fred_DEXINUS.csv` | FRED, USD/INR | Holiday `.` rows; newest 2026-08-28 |
| `fred_DGS30.csv`, `fred_DGS10.csv`, `fred_DGS2.csv` | FRED, Treasury yields | Normal live series |
| `fred_SOFR.csv`, `fred_DCOILWTICO.csv` | FRED, SOFR and WTI | Normal live series |
| `fred_DSWP30.csv`, `fred_DSWP10.csv` | FRED, 30y/10y swap rates | **The most important fixture here.** A clean HTTP 200 with valid CSV whose newest observation is **2016-10-28**. Every signal except the date says healthy. This is what a dead endpoint looks like. |
| `gold_api_XAU.json`, `gold_api_XAG.json` | gold-api.com | USD/ozt spot; ISO datetime in `updatedAt` |
| `ibjarates.html` | ibjarates.com | Kept whole, not trimmed: the parser reads JSON out of the `HdnGold`/`HdnSilver` hidden inputs, and a *real* page is what makes the "page shape changed" test meaningful. 85 observations, newest 04/09/2026, `purity916/purity999` = 0.91600 exactly. |
| `mfapi_122639_live.json` | api.mfapi.in | A live fund. The scheme code is arbitrary and public. |
| `mfapi_100027_dead.json` | api.mfapi.in | A **dead fund** — newest NAV 29-05-2008. A stale series is not a fetch failure, and the two must be distinguishable. |
| `archive_metadata_real.json` | archive.org | Item `ec-08-1904-b` holds `EC_08_1904_B.pdf` — different case *and* separators, so a filename must never be built from an item id. |
| `archive_metadata_bogus_id.json` | archive.org | A non-existent item answers **HTTP 200 with `{}`**, not 404. Status codes cannot detect a bad id. |
| `sanskritdocs_noUA.txt`, `sanskritdocs_withUA.html` | sanskritdocuments.org | **Byte-identical.** Kept as the evidence that a documented "HTTP 406 without a browser User-Agent" rule did not reproduce. |
