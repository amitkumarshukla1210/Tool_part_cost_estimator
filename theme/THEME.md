# Design to Cost theme: apply to Part Cost Estimator

Make every page of this app look like Amit's "Design to Cost" platform.

## Files
- `dtc-theme.css`: colours, font, header, buttons, cards, form fields, costing tables
- `logo.png`: the DC logo (96×96 PNG), shown 42 px high in the header and also used as the favicon

## Rules
0. **Software name is "Design to Cost"** everywhere: header, browser tab title, README title, footer ("© Design to Cost"), PDF/Excel report headers. "Part Cost Estimator" is only the name of this module, shown as the small tagline.
1. Link `dtc-theme.css` on every page and remove the old colours/fonts from `style.css` (keep only layout specific to this app).
2. **Header:** `logo.png` on the left, then the name **"Design to Cost"** in bold navy (`.brand-text .name`), exactly like the Design to Cost page. Small tagline under it: "Part Cost Estimator". Nav links on the right (Estimate, Master data, Help). Browser tab title: "Design to Cost — Part Cost Estimator".
3. **Colours:** navy `#152238` text, blue `#1f5fa8` primary, orange `#e07b1f` only as a small accent. Don't add new colours; use the CSS variables.
4. **Font:** Segoe UI for the page, Arial 12 px inside tables.
5. **Tables:** wrap in `.table-wrap`, use `class="cost-table"`: dark navy sticky header, alternating light-blue rows.
   - Cells the user types into: yellow (`td.input`)
   - Calculated cells: grey italic (`td.calc`)
   - Totals row: `tr.total`
6. **Sections:** small uppercase `.kicker` above each `h2`, inside `.section-head`.
7. **Buttons:** `.btn .btn-primary` for main actions, `.btn .btn-outline` for secondary.
8. The 3D viewer sits in a `.card`.
