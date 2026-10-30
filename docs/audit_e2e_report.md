# End-to-end audit report

Run on the current code, 2026-10-30 12:51, 868 calls in 28.5 min.

| Case | Part type | Tools | RM INR | Tool CAPEX INR | Part cost INR | Findings |
|---|---|---|---|---|---|---|
| plastic_low | plastic | 1 | 11.81 | 166,766.31 | 18.35 | none |
| plastic_high | plastic | 1 | 6.28 | 2,767,258.09 | 9.50 | none |
| plastic_large | plastic | 1 | 1,532.27 | 14,752,089.46 | 1,997.75 | none |
| insert_moulding | plastic | 1 | 13.44 | 145,459.37 | 18.66 | none |
| diecast_low | die_casting | 1 | 48.08 | 581,744.62 | 92.77 | none |
| diecast_high | die_casting | 1 | 48.80 | 25,610,194.39 | 78.07 | none |
| foundry | foundry | 1 | 19.54 | 186,030.31 | 210.34 | none |
| sheet_multistage | sheet_metal | 3 | 15.87 | 531,134.17 | 25.45 | none |
| sheet_progressive_high | sheet_metal | 1 | 6.50 | 1,466,153.29 | 8.75 | none |
| sheet_drawn_large | sheet_metal | 3 | 1,240.73 | 13,515,000.18 | 1,603.03 | none |
| sheet_channel_large | sheet_metal | 3 | 1,201.94 | 6,481,005.84 | 1,561.27 | none |
| eps | eps | 1 | 0.15 | 359,364.06 | 25.84 | none |
| blow | blow | 1 | 4.05 | 2,345,193.53 | 7.29 | none |
| machined_shaft | machined | - | 86.29 | 12,000.00 | 182.99 | none |
| machined_block | machined | - | 132.37 | 40,000.00 | 219.83 | none |

## Findings (0)

None.

## Slowest calls

- 37 s plastic_high `/api/parts/2/tool-design.zip`
- 34 s sheet_multistage `/api/parts/12/tool-design.zip`
- 31 s sheet_drawn_large `/api/parts/14/tool-design.zip`
- 31 s sheet_channel_large `/api/parts/15/tool-design.zip`
- 28 s plastic_high `/api/parts/2/tool-design.pdf`
- 26 s plastic_large `/api/parts/3/tool-design.zip`
- 24 s plastic_large `/api/parts/3/tool-design.pdf`
- 18 s plastic_large `/api/parts/3/tool-design.png`
- 17 s plastic_high `/api/parts/2/tool-design.png`
- 16 s diecast_low `/api/parts/9/tool-design.zip`
- 14 s sheet_progressive_high `/api/parts/13/tool-design.zip`
- 13 s plastic_low `/api/parts/1/tool-design.zip`
- 13 s plastic_large `/api/parts/3/tool-design.step`
- 13 s plastic_large `/api/parts/3/drawing-data`
- 13 s plastic_large `/api/parts/3/drawing-data`
