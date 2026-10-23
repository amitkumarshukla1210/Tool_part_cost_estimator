# End-to-end audit: every tool group, low and high capacity

Run on 2026-10-23 with `python scripts/audit_e2e.py` (sample parts in `samples/audit/`, made by `samples/make_audit_samples.py`).
Each case goes from 3D upload to the supplier ZIP; every file is downloaded and opened again. Example rates and rules are still EXAMPLE values.

**14 of 14 cases passed all steps.**

| Case | Group | Capacity | Result | Made parts | 3D standard parts | Force (t) | Press / base | Steel (kg) | Seconds |
|---|---|---|---|---|---|---|---|---|---|
| plastic_low | plastic | low | PASS | 10 | 47 |  | - | 136.2 | 92 |
| plastic_high | plastic | high | PASS | 10 | 276 |  | - | 12478.6 | 1578 |
| diecast_low | die casting | low | PASS | 10 | 61 |  | - | 827.6 | 114 |
| diecast_high | die casting | high | PASS | 10 | 289 |  | - | 11246.5 | 2466 |
| foundry_low | foundry | low | PASS | 9 | 0 |  | - | 10.7 | 8 |
| foundry_high | foundry | high | PASS | 10 | 6 |  | - | 395.9 | 14 |
| sheet_progressive_low | sheet metal progressive | low | PASS | 9 | 35 | 11.4 | Mechanical / servo press 63 t | 88.0 | 48 |
| sheet_stage_low | sheet metal stage | low | PASS | 15 | 60 | 11.4 | Mechanical / servo press 63 t | 118.2 | 55 |
| sheet_progressive_high | sheet metal progressive | high | PASS | 10 | 82 | 145.7 | Mechanical / servo press 315 t | 2071.8 | 125 |
| sheet_stage_high | sheet metal stage | high | PASS | 16 | 144 | 145.7 | Power press 100 t, Power press 200 t | 1504.4 | 139 |
| eps_low | EPS | low | PASS | 4 | 42 |  | - | 1782.6 | 78 |
| eps_high | EPS | high | PASS | 4 | 38 |  | - | 7275.8 | 323 |
| blow_low | blow | low | PASS | 4 | 26 |  | - | 133.5 | 50 |
| blow_high | blow | high | PASS | 4 | 34 |  | - | 353.0 | 103 |

## plastic_low (plastic, low capacity): PASS

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 1 | 0.9 |
| 2 Part has a 3D file, revision A and geometry | ok | 19 cm³, bbox {'length': 80.0, 'width': 50.0, 'height': 20.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.2 |
| 4 Tool and mould cost (BOM costed) | ok | tool cost INR 0, cavities None | 0.4 |
| 5 Design pack: Excel, PDF, PPT, 3D report, drawings, STEP | ok | 11 files, 26 s | 26.2 |
| 6 Generate the production tool design | ok | {'id': 1, 'part_id': 1, 'version': 1, 'rev_label': 'A', 'status': 'draft', 'kind': 'mould', 'part_type': 'plastic', 'country': 'IN', 'as_of': '2026-10', 'summary': {'mould_base': '2025', 'cavities': 1 | 33.0 |
| 7 Tool design: no overlaps, valid solids | ok | 10 made parts, 47 standard 3D parts | 0.0 |
| 8 BOM: made parts with stock, weight, machining; bought-out list | ok | 9 part numbers, 10 bought-out lines, 136.2 kg steel | 0.0 |
| 9 Tool part drawings (PDF, DXF) and STEP of every made part | ok | 9 part numbers: PDF + DXF + STEP each | 11.8 |
| 10 Downloaded STEP opens again as a valid solid | ok | PLASTIC_LOW-M-01 re-imports, 1942 cm³ | 0.0 |
| 11 3D viewer data (measure / view) | ok | 58 components for the 3D viewer | 0.8 |
| 12 Correct a component by STEP upload (round trip) | ok | revision B after upload, recalculated | 1.9 |
| 13 Toolmaker review signed | ok | 14 review items signed | 0.1 |
| 14 Release the design (drawing revision A) | ok | released | 1.4 |
| 15 Purchase orders: raw material, machining, bought-out (Excel + PDF) | ok | workbook 11 sheets, PO-1 9 lines, 3 PO PDFs + assembly sheet | 1.6 |
| 16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly) | ok | 34 files, 885 KB | 13.4 |

## plastic_high (plastic, high capacity): PASS

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 2 | 0.6 |
| 2 Part has a 3D file, revision A and geometry | ok | 2982 cm³, bbox {'length': 900.0, 'width': 500.0, 'height': 150.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.3 |
| 4 Tool and mould cost (BOM costed) | ok | tool cost INR 0, cavities None | 0.4 |
| 5 Design pack: Excel, PDF, PPT, 3D report, drawings, STEP | ok | 11 files, 13 s | 12.6 |
| 6 Generate the production tool design | ok | {'id': 2, 'part_id': 2, 'version': 1, 'rev_label': 'A', 'status': 'draft', 'kind': 'mould', 'part_type': 'plastic', 'country': 'IN', 'as_of': '2026-10', 'summary': {'mould_base': '120140', 'cavities': | 379.3 |
| 7 Tool design: no overlaps, valid solids | ok | 10 made parts, 276 standard 3D parts | 0.0 |
| 8 BOM: made parts with stock, weight, machining; bought-out list | ok | 9 part numbers, 10 bought-out lines, 12478.6 kg steel | 0.0 |
| 9 Tool part drawings (PDF, DXF) and STEP of every made part | ok | 9 part numbers: PDF + DXF + STEP each | 569.3 |
| 10 Downloaded STEP opens again as a valid solid | ok | PLASTIC_HIGH-M-01 re-imports, 264048 cm³ | 0.1 |
| 11 3D viewer data (measure / view) | ok | 287 components for the 3D viewer | 10.8 |
| 12 Correct a component by STEP upload (round trip) | ok | revision B after upload, recalculated | 30.6 |
| 13 Toolmaker review signed | ok | 14 review items signed | 0.1 |
| 14 Release the design (drawing revision A) | ok | released | 31.1 |
| 15 Purchase orders: raw material, machining, bought-out (Excel + PDF) | ok | workbook 11 sheets, PO-1 9 lines, 3 PO PDFs + assembly sheet | 15.8 |
| 16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly) | ok | 34 files, 4002 KB | 526.9 |

## diecast_low (die casting, low capacity): PASS

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 3 | 0.6 |
| 2 Part has a 3D file, revision A and geometry | ok | 24 cm³, bbox {'length': 70.0, 'width': 50.0, 'height': 25.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.3 |
| 4 Tool and mould cost (BOM costed) | ok | tool cost INR 0, cavities None | 0.4 |
| 5 Design pack: Excel, PDF, PPT, 3D report, drawings, STEP | ok | 11 files, 11 s | 11.5 |
| 6 Generate the production tool design | ok | {'id': 3, 'part_id': 3, 'version': 1, 'rev_label': 'A', 'status': 'draft', 'kind': 'mould', 'part_type': 'die_casting', 'country': 'IN', 'as_of': '2026-10', 'summary': {'mould_base': '4040', 'cavities | 49.0 |
| 7 Tool design: no overlaps, valid solids | ok | 10 made parts, 61 standard 3D parts | 0.0 |
| 8 BOM: made parts with stock, weight, machining; bought-out list | ok | 9 part numbers, 6 bought-out lines, 827.6 kg steel | 0.0 |
| 9 Tool part drawings (PDF, DXF) and STEP of every made part | ok | 9 part numbers: PDF + DXF + STEP each | 22.7 |
| 10 Downloaded STEP opens again as a valid solid | ok | DIECAST_LOW-M-01 re-imports, 18576 cm³ | 0.1 |
| 11 3D viewer data (measure / view) | ok | 72 components for the 3D viewer | 1.1 |
| 12 Correct a component by STEP upload (round trip) | ok | revision B after upload, recalculated | 2.6 |
| 13 Toolmaker review signed | ok | 14 review items signed | 0.1 |
| 14 Release the design (drawing revision A) | ok | released | 2.1 |
| 15 Purchase orders: raw material, machining, bought-out (Excel + PDF) | ok | workbook 11 sheets, PO-1 9 lines, 3 PO PDFs + assembly sheet | 1.8 |
| 16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly) | ok | 34 files, 982 KB | 21.4 |

## diecast_high (die casting, high capacity): PASS

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 4 | 0.7 |
| 2 Part has a 3D file, revision A and geometry | ok | 2538 cm³, bbox {'length': 650.0, 'width': 450.0, 'height': 120.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.3 |
| 4 Tool and mould cost (BOM costed) | ok | tool cost INR 0, cavities None | 0.4 |
| 5 Design pack: Excel, PDF, PPT, 3D report, drawings, STEP | ok | 11 files, 12 s | 11.9 |
| 6 Generate the production tool design | ok | {'id': 4, 'part_id': 4, 'version': 1, 'rev_label': 'A', 'status': 'draft', 'kind': 'mould', 'part_type': 'die_casting', 'country': 'IN', 'as_of': '2026-10', 'summary': {'mould_base': '100120', 'caviti | 514.9 |
| 7 Tool design: no overlaps, valid solids | ok | 10 made parts, 289 standard 3D parts | 0.0 |
| 8 BOM: made parts with stock, weight, machining; bought-out list | ok | 9 part numbers, 6 bought-out lines, 11246.5 kg steel | 0.0 |
| 9 Tool part drawings (PDF, DXF) and STEP of every made part | ok | 9 part numbers: PDF + DXF + STEP each | 899.2 |
| 10 Downloaded STEP opens again as a valid solid | ok | DIECAST_HIGH-M-01 re-imports, 226406 cm³ | 0.1 |
| 11 3D viewer data (measure / view) | ok | 300 components for the 3D viewer | 12.2 |
| 12 Correct a component by STEP upload (round trip) | ok | revision B after upload, recalculated | 35.7 |
| 13 Toolmaker review signed | ok | 14 review items signed | 0.1 |
| 14 Release the design (drawing revision A) | ok | released | 36.2 |
| 15 Purchase orders: raw material, machining, bought-out (Excel + PDF) | ok | workbook 11 sheets, PO-1 9 lines, 3 PO PDFs + assembly sheet | 17.5 |
| 16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly) | ok | 34 files, 3817 KB | 936.7 |

## foundry_low (foundry, low capacity): PASS

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 5 | 0.2 |
| 2 Part has a 3D file, revision A and geometry | ok | 234 cm³, bbox {'length': 120.0, 'width': 80.0, 'height': 50.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.1 |
| 6 Generate the production tool design | ok | {'id': 5, 'part_id': 5, 'version': 1, 'rev_label': 'A', 'status': 'draft', 'kind': 'foundry', 'part_type': 'foundry', 'country': 'IN', 'as_of': '2026-10', 'summary': {'notes': 'Pattern: cope half is t | 2.8 |
| 7 Tool design: no overlaps, valid solids | ok | 9 made parts, 0 standard 3D parts | 0.0 |
| 8 BOM: made parts with stock, weight, machining; bought-out list | ok | 9 part numbers, 1 bought-out lines, 10.7 kg steel | 0.0 |
| 9 Tool part drawings (PDF, DXF) and STEP of every made part | ok | 9 part numbers: PDF + DXF + STEP each | 1.6 |
| 10 Downloaded STEP opens again as a valid solid | ok | FOUNDRY_LOW-F-01 re-imports, 259 cm³ | 0.0 |
| 11 3D viewer data (measure / view) | ok | 13 components for the 3D viewer | 0.2 |
| 12 Correct a component by STEP upload (round trip) | ok | revision B after upload, recalculated | 0.6 |
| 13 Toolmaker review signed | ok | 6 review items signed | 0.0 |
| 14 Release the design (drawing revision A) | ok | released | 0.3 |
| 15 Purchase orders: raw material, machining, bought-out (Excel + PDF) | ok | workbook 11 sheets, PO-1 9 lines, 3 PO PDFs + assembly sheet | 0.6 |
| 16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly) | ok | 34 files, 445 KB | 1.9 |

## foundry_high (foundry, high capacity): PASS

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 6 | 0.2 |
| 2 Part has a 3D file, revision A and geometry | ok | 19932 cm³, bbox {'length': 700.0, 'width': 450.0, 'height': 250.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.1 |
| 6 Generate the production tool design | ok | {'id': 6, 'part_id': 6, 'version': 1, 'rev_label': 'A', 'status': 'draft', 'kind': 'foundry', 'part_type': 'foundry', 'country': 'IN', 'as_of': '2026-10', 'summary': {'notes': 'Pattern: cope half is t | 6.2 |
| 7 Tool design: no overlaps, valid solids | ok | 10 made parts, 6 standard 3D parts | 0.0 |
| 8 BOM: made parts with stock, weight, machining; bought-out list | ok | 10 part numbers, 3 bought-out lines, 395.9 kg steel | 0.0 |
| 9 Tool part drawings (PDF, DXF) and STEP of every made part | ok | 10 part numbers: PDF + DXF + STEP each | 1.9 |
| 10 Downloaded STEP opens again as a valid solid | ok | FOUNDRY_HIGH-F-01 re-imports, 592 cm³ | 0.0 |
| 11 3D viewer data (measure / view) | ok | 20 components for the 3D viewer | 0.3 |
| 12 Correct a component by STEP upload (round trip) | ok | revision B after upload, recalculated | 1.1 |
| 13 Toolmaker review signed | ok | 6 review items signed | 0.1 |
| 14 Release the design (drawing revision A) | ok | released | 0.9 |
| 15 Purchase orders: raw material, machining, bought-out (Excel + PDF) | ok | workbook 11 sheets, PO-1 10 lines, 3 PO PDFs + assembly sheet | 0.8 |
| 16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly) | ok | 37 files, 733 KB | 2.2 |

## sheet_progressive_low (sheet metal progressive, low capacity): PASS

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 7 | 0.1 |
| 2 Part has a 3D file, revision A and geometry | ok | 4 cm³, bbox {'length': 60.0, 'width': 30.0, 'height': 20.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.1 |
| 5 Design pack: Excel, PDF, PPT, 3D report, drawings, STEP | ok | 14 files, 3 s | 3.5 |
| 6 Generate the production tool design | ok | {'id': 7, 'part_id': 7, 'version': 1, 'rev_label': 'A', 'status': 'draft', 'kind': 'sheet_metal', 'part_type': 'sheet_metal', 'country': 'IN', 'as_of': '2026-10', 'summary': {'fea': {'available': True | 7.2 |
| 7 Tool design: no overlaps, valid solids | ok | 9 made parts, 35 standard 3D parts | 0.0 |
| 8 BOM: made parts with stock, weight, machining; bought-out list | ok | 8 part numbers, 6 bought-out lines, 88.0 kg steel | 0.0 |
| 9 Tool part drawings (PDF, DXF) and STEP of every made part | ok | 8 part numbers: PDF + DXF + STEP each | 1.4 |
| 10 Downloaded STEP opens again as a valid solid | ok | SHEET_PROGRESSIVE_LOW-P-01 re-imports, 814 cm³ | 0.1 |
| 11 3D viewer data (measure / view) | ok | 46 components for the 3D viewer | 0.6 |
| 12 Correct a component by STEP upload (round trip) | ok | revision B after upload, recalculated | 1.4 |
| 13 Toolmaker review signed | ok | 10 review items signed | 0.0 |
| 14 Release the design (drawing revision A) | ok | released | 1.1 |
| 15 Purchase orders: raw material, machining, bought-out (Excel + PDF) | ok | workbook 11 sheets, PO-1 8 lines, 3 PO PDFs + assembly sheet | 1.5 |
| 16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly) | ok | 31 files, 676 KB | 2.9 |
| 17 Progressive vs stage comparison and package | ok | Progressive die cheaper by INR 0.907; package 1647 KB | 28.4 |

## sheet_stage_low (sheet metal stage, low capacity): PASS

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 8 | 0.1 |
| 2 Part has a 3D file, revision A and geometry | ok | 4 cm³, bbox {'length': 60.0, 'width': 30.0, 'height': 20.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.1 |
| 5 Design pack: Excel, PDF, PPT, 3D report, drawings, STEP | ok | 15 files, 3 s | 2.9 |
| 6 Generate the production tool design | ok | {'id': 10, 'part_id': 8, 'version': 1, 'rev_label': 'A', 'status': 'draft', 'kind': 'sheet_metal', 'part_type': 'sheet_metal', 'country': 'IN', 'as_of': '2026-10', 'summary': {'fea': {'available': Tru | 10.0 |
| 7 Tool design: no overlaps, valid solids | ok | 15 made parts, 60 standard 3D parts | 0.0 |
| 8 BOM: made parts with stock, weight, machining; bought-out list | ok | 14 part numbers, 7 bought-out lines, 118.2 kg steel | 0.0 |
| 9 Tool part drawings (PDF, DXF) and STEP of every made part | ok | 14 part numbers: PDF + DXF + STEP each | 2.8 |
| 10 Downloaded STEP opens again as a valid solid | ok | SHEET_STAGE_LOW-S1-01 re-imports, 475 cm³ | 0.0 |
| 11 3D viewer data (measure / view) | ok | 77 components for the 3D viewer | 1.2 |
| 12 Correct a component by STEP upload (round trip) | ok | revision B after upload, recalculated | 2.5 |
| 13 Toolmaker review signed | ok | 10 review items signed | 0.1 |
| 14 Release the design (drawing revision A) | ok | released | 2.3 |
| 15 Purchase orders: raw material, machining, bought-out (Excel + PDF) | ok | workbook 11 sheets, PO-1 14 lines, 3 PO PDFs + assembly sheet | 2.1 |
| 16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly) | ok | 49 files, 942 KB | 4.2 |
| 17 Progressive vs stage comparison and package | ok | Progressive die cheaper by INR 0.907; package 1645 KB | 26.9 |

## sheet_progressive_high (sheet metal progressive, high capacity): PASS

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 9 | 0.1 |
| 2 Part has a 3D file, revision A and geometry | ok | 366 cm³, bbox {'length': 500.0, 'width': 250.0, 'height': 60.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.1 |
| 5 Design pack: Excel, PDF, PPT, 3D report, drawings, STEP | ok | 14 files, 5 s | 5.4 |
| 6 Generate the production tool design | ok | {'id': 13, 'part_id': 9, 'version': 1, 'rev_label': 'A', 'status': 'draft', 'kind': 'sheet_metal', 'part_type': 'sheet_metal', 'country': 'IN', 'as_of': '2026-10', 'summary': {'fea': {'available': Tru | 21.4 |
| 7 Tool design: no overlaps, valid solids | ok | 10 made parts, 82 standard 3D parts | 0.0 |
| 8 BOM: made parts with stock, weight, machining; bought-out list | ok | 9 part numbers, 6 bought-out lines, 2071.8 kg steel | 0.0 |
| 9 Tool part drawings (PDF, DXF) and STEP of every made part | ok | 9 part numbers: PDF + DXF + STEP each | 3.5 |
| 10 Downloaded STEP opens again as a valid solid | ok | SHEET_PROGRESSIVE_HIGH-P-01 re-imports, 26499 cm³ | 0.1 |
| 11 3D viewer data (measure / view) | ok | 94 components for the 3D viewer | 1.6 |
| 12 Correct a component by STEP upload (round trip) | ok | revision B after upload, recalculated | 5.4 |
| 13 Toolmaker review signed | ok | 10 review items signed | 0.1 |
| 14 Release the design (drawing revision A) | ok | released | 4.1 |
| 15 Purchase orders: raw material, machining, bought-out (Excel + PDF) | ok | workbook 11 sheets, PO-1 9 lines, 3 PO PDFs + assembly sheet | 2.6 |
| 16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly) | ok | 34 files, 1237 KB | 6.4 |
| 17 Progressive vs stage comparison and package | ok | Progressive die cheaper by INR 46.588; package 3173 KB | 74.2 |

## sheet_stage_high (sheet metal stage, high capacity): PASS

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 10 | 0.1 |
| 2 Part has a 3D file, revision A and geometry | ok | 366 cm³, bbox {'length': 500.0, 'width': 250.0, 'height': 60.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.1 |
| 5 Design pack: Excel, PDF, PPT, 3D report, drawings, STEP | ok | 15 files, 3 s | 3.4 |
| 6 Generate the production tool design | ok | {'id': 16, 'part_id': 10, 'version': 1, 'rev_label': 'A', 'status': 'draft', 'kind': 'sheet_metal', 'part_type': 'sheet_metal', 'country': 'IN', 'as_of': '2026-10', 'summary': {'fea': {'available': Tr | 27.1 |
| 7 Tool design: no overlaps, valid solids | ok | 16 made parts, 144 standard 3D parts | 0.0 |
| 8 BOM: made parts with stock, weight, machining; bought-out list | ok | 15 part numbers, 7 bought-out lines, 1504.4 kg steel | 0.0 |
| 9 Tool part drawings (PDF, DXF) and STEP of every made part | ok | 15 part numbers: PDF + DXF + STEP each | 6.2 |
| 10 Downloaded STEP opens again as a valid solid | ok | SHEET_STAGE_HIGH-S1-01 re-imports, 5676 cm³ | 0.1 |
| 11 3D viewer data (measure / view) | ok | 162 components for the 3D viewer | 3.7 |
| 12 Correct a component by STEP upload (round trip) | ok | revision B after upload, recalculated | 8.2 |
| 13 Toolmaker review signed | ok | 10 review items signed | 0.1 |
| 14 Release the design (drawing revision A) | ok | released | 5.7 |
| 15 Purchase orders: raw material, machining, bought-out (Excel + PDF) | ok | workbook 11 sheets, PO-1 15 lines, 3 PO PDFs + assembly sheet | 5.6 |
| 16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly) | ok | 52 files, 1905 KB | 9.7 |
| 17 Progressive vs stage comparison and package | ok | Progressive die cheaper by INR 46.588; package 3171 KB | 69.4 |

## eps_low (EPS, low capacity): PASS

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 11 | 0.4 |
| 2 Part has a 3D file, revision A and geometry | ok | 1086 cm³, bbox {'length': 200.0, 'width': 150.0, 'height': 80.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.2 |
| 4 Tool and mould cost (BOM costed) | ok | tool cost INR 0, cavities None | 0.4 |
| 6 Generate the production tool design | ok | {'id': 19, 'part_id': 11, 'version': 1, 'rev_label': 'A', 'status': 'draft', 'kind': 'mould', 'part_type': 'eps', 'country': 'IN', 'as_of': '2026-10', 'summary': {'mould_base': '0806', 'cavities': 2,  | 68.7 |
| 7 Tool design: no overlaps, valid solids | ok | 4 made parts, 42 standard 3D parts | 0.0 |
| 8 BOM: made parts with stock, weight, machining; bought-out list | ok | 4 part numbers, 7 bought-out lines, 1782.6 kg steel | 0.0 |
| 9 Tool part drawings (PDF, DXF) and STEP of every made part | ok | 4 part numbers: PDF + DXF + STEP each | 1.2 |
| 10 Downloaded STEP opens again as a valid solid | ok | EPS_LOW-M-01 re-imports, 72545 cm³ | 0.0 |
| 11 3D viewer data (measure / view) | ok | 47 components for the 3D viewer | 0.6 |
| 12 Correct a component by STEP upload (round trip) | ok | revision B after upload, recalculated | 1.3 |
| 13 Toolmaker review signed | ok | 14 review items signed | 0.1 |
| 14 Release the design (drawing revision A) | ok | released | 1.1 |
| 15 Purchase orders: raw material, machining, bought-out (Excel + PDF) | ok | workbook 11 sheets, PO-1 4 lines, 3 PO PDFs + assembly sheet | 1.4 |
| 16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly) | ok | 19 files, 518 KB | 2.2 |

## eps_high (EPS, high capacity): PASS

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 12 | 0.5 |
| 2 Part has a 3D file, revision A and geometry | ok | 52293 cm³, bbox {'length': 1000.0, 'width': 600.0, 'height': 400.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.3 |
| 4 Tool and mould cost (BOM costed) | ok | tool cost INR 0, cavities None | 0.6 |
| 6 Generate the production tool design | ok | {'id': 20, 'part_id': 12, 'version': 1, 'rev_label': 'A', 'status': 'draft', 'kind': 'mould', 'part_type': 'eps', 'country': 'IN', 'as_of': '2026-10', 'summary': {'mould_base': '1412', 'cavities': 1,  | 66.7 |
| 7 Tool design: no overlaps, valid solids | ok | 4 made parts, 38 standard 3D parts | 0.0 |
| 8 BOM: made parts with stock, weight, machining; bought-out list | ok | 4 part numbers, 7 bought-out lines, 7275.8 kg steel | 0.0 |
| 9 Tool part drawings (PDF, DXF) and STEP of every made part | ok | 4 part numbers: PDF + DXF + STEP each | 128.9 |
| 10 Downloaded STEP opens again as a valid solid | ok | EPS_HIGH-M-01 re-imports, 209622 cm³ | 0.0 |
| 11 3D viewer data (measure / view) | ok | 43 components for the 3D viewer | 0.6 |
| 12 Correct a component by STEP upload (round trip) | ok | revision B after upload, recalculated | 1.6 |
| 13 Toolmaker review signed | ok | 14 review items signed | 0.1 |
| 14 Release the design (drawing revision A) | ok | released | 1.3 |
| 15 Purchase orders: raw material, machining, bought-out (Excel + PDF) | ok | workbook 11 sheets, PO-1 4 lines, 3 PO PDFs + assembly sheet | 1.2 |
| 16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly) | ok | 19 files, 1264 KB | 120.9 |

## blow_low (blow, low capacity): PASS

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 13 | 0.3 |
| 2 Part has a 3D file, revision A and geometry | ok | 17 cm³, bbox {'length': 150.0, 'width': 60.0, 'height': 60.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.2 |
| 4 Tool and mould cost (BOM costed) | ok | tool cost INR 0, cavities None | 0.4 |
| 6 Generate the production tool design | ok | {'id': 21, 'part_id': 13, 'version': 1, 'rev_label': 'A', 'status': 'draft', 'kind': 'mould', 'part_type': 'blow', 'country': 'IN', 'as_of': '2026-10', 'summary': {'mould_base': '7015', 'cavities': 1, | 10.3 |
| 7 Tool design: no overlaps, valid solids | ok | 4 made parts, 26 standard 3D parts | 0.0 |
| 8 BOM: made parts with stock, weight, machining; bought-out list | ok | 4 part numbers, 6 bought-out lines, 133.5 kg steel | 0.0 |
| 9 Tool part drawings (PDF, DXF) and STEP of every made part | ok | 4 part numbers: PDF + DXF + STEP each | 16.1 |
| 10 Downloaded STEP opens again as a valid solid | ok | BLOW_LOW-M-01 re-imports, 5012 cm³ | 0.0 |
| 11 3D viewer data (measure / view) | ok | 31 components for the 3D viewer | 0.4 |
| 12 Correct a component by STEP upload (round trip) | ok | revision B after upload, recalculated | 1.7 |
| 13 Toolmaker review signed | ok | 14 review items signed | 0.1 |
| 14 Release the design (drawing revision A) | ok | released | 1.3 |
| 15 Purchase orders: raw material, machining, bought-out (Excel + PDF) | ok | workbook 11 sheets, PO-1 4 lines, 3 PO PDFs + assembly sheet | 0.9 |
| 16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly) | ok | 19 files, 788 KB | 18.3 |

## blow_high (blow, high capacity): PASS

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 14 | 0.4 |
| 2 Part has a 3D file, revision A and geometry | ok | 211 cm³, bbox {'length': 300.0, 'width': 150.0, 'height': 150.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.3 |
| 4 Tool and mould cost (BOM costed) | ok | tool cost INR 0, cavities None | 0.4 |
| 6 Generate the production tool design | ok | {'id': 22, 'part_id': 14, 'version': 1, 'rev_label': 'A', 'status': 'draft', 'kind': 'mould', 'part_type': 'blow', 'country': 'IN', 'as_of': '2026-10', 'summary': {'mould_base': '6030', 'cavities': 1, | 25.8 |
| 7 Tool design: no overlaps, valid solids | ok | 4 made parts, 34 standard 3D parts | 0.0 |
| 8 BOM: made parts with stock, weight, machining; bought-out list | ok | 4 part numbers, 6 bought-out lines, 353.0 kg steel | 0.0 |
| 9 Tool part drawings (PDF, DXF) and STEP of every made part | ok | 4 part numbers: PDF + DXF + STEP each | 36.8 |
| 10 Downloaded STEP opens again as a valid solid | ok | BLOW_HIGH-M-01 re-imports, 10813 cm³ | 0.0 |
| 11 3D viewer data (measure / view) | ok | 39 components for the 3D viewer | 0.5 |
| 12 Correct a component by STEP upload (round trip) | ok | revision B after upload, recalculated | 2.2 |
| 13 Toolmaker review signed | ok | 14 review items signed | 0.1 |
| 14 Release the design (drawing revision A) | ok | released | 1.7 |
| 15 Purchase orders: raw material, machining, bought-out (Excel + PDF) | ok | workbook 11 sheets, PO-1 4 lines, 3 PO PDFs + assembly sheet | 1.4 |
| 16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly) | ok | 19 files, 1041 KB | 33.4 |
