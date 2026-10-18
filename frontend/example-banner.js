// Warning banner for every cost that uses a rate still marked EXAMPLE (same wording as the Excel / PDF exports).
window.EXAMPLE_WARNING = "Uses example rates – not for negotiation";
window.exampleBanner = (detail = "") =>
  `<div class="example-banner" role="alert"><b>${window.EXAMPLE_WARNING}</b>${detail ? `<span>${detail}</span>` : ""}</div>`;
