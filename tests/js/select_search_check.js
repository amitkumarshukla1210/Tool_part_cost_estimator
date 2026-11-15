// Browser check of frontend/select-search.js (run by tests/test_select_search.py).
const { chromium } = require("playwright");
const path = require("path");
(async () => {
  const js = path.resolve(__dirname, "../../frontend/select-search.js");
  const css = path.resolve(__dirname, "../../frontend/style.css");
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const grades = ["PP (polypropylene)", "ABS", "PC (polycarbonate)", "PC/ABS", "PA6", "PA66 GF30", "PBT GF30", "POM (acetal)",
    "Aluminium ADC12 / A383", "Aluminium A380", "Zinc Zamak 3", "Magnesium AZ91D", "Grey cast iron FG260"];
  const opts = grades.map((g, i) => `<option value="${g}">${g} · M-${100 + i}</option>`).join("");
  await page.setContent(`<html><body>
    <select id="big"><option value="">—</option><optgroup label="Part materials">${opts}</optgroup>
      <optgroup label="Insert materials"><option value="Brass insert">Brass insert</option></optgroup></select>
    <select id="small"><option>a</option><option>b</option></select>
    <div id="wrap" style="width:300px;height:120px;overflow:auto"><div style="width:900px;height:600px;padding:20px">
      <select id="inner">${opts}</select></div></div>
    </body></html>`);
  await page.addStyleTag({ path: css });
  await page.addScriptTag({ path: js });
  await page.evaluate(() => { window.changes = 0; document.getElementById("big").addEventListener("change", () => window.changes++); });
  const fail = (m) => { console.log("FAIL " + m); process.exitCode = 1; };
  const visible = () => page.$$eval(".ss-item", (els) => els.filter((e) => !e.hidden).map((e) => e.textContent));

  await page.click("#big");
  if (!(await page.$(".ss-pop"))) fail("no search popup on a long list");
  if ((await visible()).length !== 15) fail("all 15 choices not shown: " + (await visible()).length);
  await page.keyboard.type("gf30");
  let v = await visible();
  if (v.length !== 2 || !v.every((t) => t.includes("GF30"))) fail("gf30 → " + JSON.stringify(v));
  await page.fill(".ss-input", "m-108");                      // code
  v = await visible();
  if (v.length !== 1 || !v[0].startsWith("Aluminium ADC12")) fail("code m-108 → " + JSON.stringify(v));
  await page.fill(".ss-input", "insert");                     // group heading
  v = await visible();
  if (v.length !== 1 || v[0] !== "Brass insert") fail("group 'insert' → " + JSON.stringify(v));
  await page.fill(".ss-input", "alum a380");                  // every word
  v = await visible();
  if (v.length !== 1) fail("alum a380 → " + JSON.stringify(v));
  await page.keyboard.press("Enter");
  if ((await page.inputValue("#big")) !== "Aluminium A380") fail("Enter did not pick: " + (await page.inputValue("#big")));
  if ((await page.evaluate(() => window.changes)) !== 1) fail("change event not fired once");
  if (await page.$(".ss-pop")) fail("popup still open after choosing");

  await page.click("#big");
  await page.fill(".ss-input", "zzz");
  if (!(await page.isVisible(".ss-empty"))) fail("'No match' not shown");
  await page.keyboard.press("Escape");
  if (await page.$(".ss-pop")) fail("Esc did not close");
  if ((await page.inputValue("#big")) !== "Aluminium A380") fail("Esc changed the value");

  await page.click("#big");
  await page.fill(".ss-input", "zamak");
  await page.click(".ss-item:not([hidden])");
  if ((await page.inputValue("#big")) !== "Zinc Zamak 3") fail("click did not pick");

  await page.focus("#big");
  await page.keyboard.press("Enter");
  if (!(await page.$(".ss-pop"))) fail("Enter on a focused list does not open the search");
  await page.click("body", { position: { x: 600, y: 500 } });
  if (await page.$(".ss-pop")) fail("click outside did not close");

  await page.click("#inner");                                // inside a scrolling table
  await page.evaluate(() => { document.getElementById("wrap").scrollLeft = 30; document.getElementById("wrap").dispatchEvent(new Event("scroll")); });
  await page.waitForTimeout(100);
  if (!(await page.$(".ss-pop"))) fail("a table scroll closed the search");
  await page.keyboard.type("az91");
  await page.keyboard.press("Enter");
  if ((await page.inputValue("#inner")) !== "Magnesium AZ91D") fail("inner pick: " + (await page.inputValue("#inner")));

  await page.evaluate((o) => { const d = document.createElement("dialog"); d.innerHTML = `<select id="dlg">${o}</select>`;
    document.body.appendChild(d); d.showModal(); }, opts);          // in a modal dialog (Rates, Dashboard)
  await page.click("#dlg");
  await page.keyboard.type("fg260");
  await page.click(".ss-item:not([hidden])");
  if ((await page.inputValue("#dlg")) !== "Grey cast iron FG260") fail("pick inside a modal dialog: " + (await page.inputValue("#dlg")));
  await page.evaluate(() => document.querySelector("dialog").close());

  await page.click("#small").catch(() => {});
  if (await page.$(".ss-pop")) fail("short list must stay the browser list");
  await browser.close();
  if (!process.exitCode) console.log("OK");
})();
