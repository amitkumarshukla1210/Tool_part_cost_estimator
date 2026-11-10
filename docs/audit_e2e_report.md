# End-to-end audit report

Run on the current code, 2026-11-10 00:08, 1150 calls in 15.3 min.

| Case | Part type | Tools | RM INR | Tool CAPEX INR | Part cost INR | Findings |
|---|---|---|---|---|---|---|
| plastic_low | plastic | 1 | 11.81 | 166,766.31 | 17.56 | none |
| plastic_high | plastic | 1 | 6.28 | 2,767,258.09 | 9.30 | none |
| plastic_large | plastic | 1 | 1,532.27 | 14,752,089.46 | 2,218.35 | none |
| insert_moulding | plastic | 1 | 13.44 | 145,459.37 | 37.83 | none |
| diecast_low | die_casting | 1 | 48.08 | 581,744.62 | 78.75 | none |
| diecast_high | die_casting | 1 | 48.80 | 25,610,194.39 | 69.18 | none |
| foundry | foundry | 1 | 19.54 | 186,030.31 | 210.34 | none |
| sheet_multistage | sheet_metal | 3 | 15.87 | 531,134.17 | 26.02 | none |
| sheet_progressive_high | sheet_metal | 1 | 6.50 | 1,466,153.29 | 8.46 | none |
| sheet_drawn_large | sheet_metal | 3 | 1,240.73 | 13,515,000.18 | 1,610.13 | none |
| sheet_channel_large | sheet_metal | 3 | 1,201.94 | 6,481,005.84 | 1,563.74 | none |
| eps | eps | 1 | 0.15 | 359,364.06 | 6.90 | none |
| blow | blow | 1 | 4.05 | 2,345,193.53 | 7.40 | none |
| machined_shaft | machined | - | 86.29 | 12,000.00 | 182.99 | none |
| machined_block | machined | - | 132.37 | 40,000.00 | 219.83 | none |

## Findings (0)

None.

## Slowest calls

- 10 s robustness `/api/parts/20/drawing-data`
