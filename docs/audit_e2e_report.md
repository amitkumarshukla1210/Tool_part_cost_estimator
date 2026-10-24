# End-to-end audit: every tool group, low and high capacity

Run on 2026-10-24 with `python scripts/audit_e2e.py` (sample parts in `samples/audit/`, made by `samples/make_audit_samples.py`).
Each case goes from 3D upload to the supplier ZIP; every file is downloaded and opened again. Example rates and rules are still EXAMPLE values.

**14 of 14 cases passed all steps.**

| Case | Group | Capacity | Result | Made parts | 3D standard parts | Force (t) | Press / base | Steel (kg) | Seconds |
|---|---|---|---|---|---|---|---|---|---|
| plastic_low | plastic | low | PASS | 10 | 47 |  | - | 136.2 | 121 |
| plastic_high | plastic | high | PASS | 10 | 276 |  | - | 12478.6 | 805 |
| diecast_low | die casting | low | PASS | 10 | 61 |  | - | 827.6 | 145 |
| diecast_high | die casting | high | PASS | 10 | 289 |  | - | 11246.5 | 1053 |
| foundry_low | foundry | low | PASS | 9 | 0 |  | - | 10.7 | 11 |
| foundry_high | foundry | high | PASS | 10 | 6 |  | - | 395.9 | 18 |
| sheet_progressive_low | sheet metal progressive | low | PASS | 9 | 35 | 11.4 | Mechanical / servo press 63 t | 88.0 | 61 |
| sheet_stage_low | sheet metal stage | low | PASS | 15 | 60 | 11.4 | Mechanical / servo press 63 t | 118.2 | 70 |
| sheet_progressive_high | sheet metal progressive | high | PASS | 10 | 82 | 145.7 | Mechanical / servo press 315 t | 2071.8 | 159 |
| sheet_stage_high | sheet metal stage | high | PASS | 16 | 144 | 145.7 | Power press 100 t, Power press 200 t | 1504.4 | 191 |
| eps_low | EPS | low | PASS | 4 | 42 |  | - | 1782.6 | 108 |
| eps_high | EPS | high | PASS | 4 | 38 |  | - | 7275.8 | 426 |
| blow_low | blow | low | PASS | 4 | 26 |  | - | 133.5 | 66 |
| blow_high | blow | high | PASS | 4 | 34 |  | - | 353.0 | 121 |

## plastic_low (plastic, low capacity): PASS

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 1 | 1.1 |
| 2 Part has a 3D file, revision A and geometry | ok | 19 cm³, bbox {'length': 80.0, 'width': 50.0, 'height': 20.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.3 |
| 4 Tool and mould cost (BOM costed) | ok | tool cost INR 0, cavities None | 0.5 |
| 5 Design pack: Excel, PDF, PPT, 3D report, drawings, STEP | ok | 11 files, 35 s | 34.6 |
| 6 Generate the production tool design | ok | {'id': 1, 'part_id': 1, 'version': 1, 'rev_label': 'A', 'status': 'draft', 'kind': 'mould', 'part_type': 'plastic', 'country': 'IN', 'as_of': '2026-10', 'summary': {'mould_base': '2025', 'base_mm': [2 | 40.1 |
| 7 Tool design: no overlaps, valid solids | ok | 10 made parts, 47 standard 3D parts | 0.0 |
| 8 BOM: made parts with stock, weight, machining; bought-out list | ok | 9 part numbers, 10 bought-out lines, 136.2 kg steel | 0.0 |
| 9 Tool part drawings (PDF, DXF) and STEP of every made part | ok | 9 part numbers: PDF + DXF + STEP each | 15.6 |
| 10 Downloaded STEP opens again as a valid solid | ok | PLASTIC_LOW-M-01 re-imports, 1942 cm³ | 0.1 |
| 10b Machine: recommended parameters of the finished tool | ok | machine not typed: the tool needs rec_tonnage_t = 30; closest Injection moulding machine 80 t | 0.0 |
| 10c Process parameters for the best part quality | ok | 16 settings, 1 quality warning(s) | 4.3 |
| 11 3D viewer data (measure / view) | ok | 58 components for the 3D viewer | 1.1 |
| 12 Correct a component by STEP upload (round trip) | ok | revision B after upload, recalculated | 2.1 |
| 13 Toolmaker review signed | ok | 16 review items signed | 0.1 |
| 14 Release the design (drawing revision A) | ok | released | 1.6 |
| 15 Purchase orders: raw material, machining, bought-out (Excel + PDF) | ok | workbook 12 sheets, PO-1 9 lines, 3 PO PDFs + assembly sheet | 2.1 |
| 16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly) | ok | 34 files, 886 KB | 16.9 |

## plastic_high (plastic, high capacity): PASS

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 2 | 0.8 |
| 2 Part has a 3D file, revision A and geometry | ok | 2982 cm³, bbox {'length': 900.0, 'width': 500.0, 'height': 150.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.4 |
| 4 Tool and mould cost (BOM costed) | ok | tool cost INR 0, cavities None | 0.5 |
| 5 Design pack: Excel, PDF, PPT, 3D report, drawings, STEP | ok | 11 files, 20 s | 19.6 |
| 6 Generate the production tool design | ok | {'id': 2, 'part_id': 2, 'version': 1, 'rev_label': 'A', 'status': 'draft', 'kind': 'mould', 'part_type': 'plastic', 'country': 'IN', 'as_of': '2026-10', 'summary': {'mould_base': '120140', 'base_mm':  | 467.9 |
| 7 Tool design: no overlaps, valid solids | ok | 10 made parts, 276 standard 3D parts | 0.0 |
| 8 BOM: made parts with stock, weight, machining; bought-out list | ok | 9 part numbers, 10 bought-out lines, 12478.6 kg steel | 0.0 |
| 9 Tool part drawings (PDF, DXF) and STEP of every made part | ok | 9 part numbers: PDF + DXF + STEP each | 87.1 |
| 10 Downloaded STEP opens again as a valid solid | ok | PLASTIC_HIGH-M-01 re-imports, 264048 cm³ | 0.1 |
| 10b Machine: recommended parameters of the finished tool | ok | machine not typed: the tool needs rec_tonnage_t = 2380; closest Injection moulding machine 2500 t | 0.0 |
| 10c Process parameters for the best part quality | ok | 16 settings, 2 quality warning(s) | 4.8 |
| 11 3D viewer data (measure / view) | ok | 287 components for the 3D viewer | 13.8 |
| 12 Correct a component by STEP upload (round trip) | ok | revision B after upload, recalculated | 38.5 |
| 13 Toolmaker review signed | ok | 16 review items signed | 0.4 |
| 14 Release the design (drawing revision A) | ok | released | 37.0 |
| 15 Purchase orders: raw material, machining, bought-out (Excel + PDF) | ok | workbook 12 sheets, PO-1 9 lines, 3 PO PDFs + assembly sheet | 18.5 |
| 16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly) | ok | 34 files, 3938 KB | 115.1 |

## diecast_low (die casting, low capacity): PASS

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 3 | 0.7 |
| 2 Part has a 3D file, revision A and geometry | ok | 24 cm³, bbox {'length': 70.0, 'width': 50.0, 'height': 25.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.3 |
| 4 Tool and mould cost (BOM costed) | ok | tool cost INR 0, cavities None | 0.5 |
| 5 Design pack: Excel, PDF, PPT, 3D report, drawings, STEP | ok | 11 files, 18 s | 17.5 |
| 6 Generate the production tool design | ok | {'id': 3, 'part_id': 3, 'version': 1, 'rev_label': 'A', 'status': 'draft', 'kind': 'mould', 'part_type': 'die_casting', 'country': 'IN', 'as_of': '2026-10', 'summary': {'mould_base': '4040', 'base_mm' | 58.0 |
| 7 Tool design: no overlaps, valid solids | ok | 10 made parts, 61 standard 3D parts | 0.0 |
| 8 BOM: made parts with stock, weight, machining; bought-out list | ok | 9 part numbers, 6 bought-out lines, 827.6 kg steel | 0.0 |
| 9 Tool part drawings (PDF, DXF) and STEP of every made part | ok | 9 part numbers: PDF + DXF + STEP each | 28.0 |
| 10 Downloaded STEP opens again as a valid solid | ok | DIECAST_LOW-M-01 re-imports, 18576 cm³ | 0.1 |
| 10b Machine: recommended parameters of the finished tool | ok | machine not typed: the tool needs rec_tonnage_t = 40; closest HPDC machine 250 t | 0.0 |
| 10c Process parameters for the best part quality | ok | 10 settings, 1 quality warning(s) | 4.0 |
| 11 3D viewer data (measure / view) | ok | 72 components for the 3D viewer | 1.3 |
| 12 Correct a component by STEP upload (round trip) | ok | revision B after upload, recalculated | 2.7 |
| 13 Toolmaker review signed | ok | 16 review items signed | 0.1 |
| 14 Release the design (drawing revision A) | ok | released | 2.3 |
| 15 Purchase orders: raw material, machining, bought-out (Excel + PDF) | ok | workbook 12 sheets, PO-1 9 lines, 3 PO PDFs + assembly sheet | 2.2 |
| 16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly) | ok | 34 files, 983 KB | 26.7 |

## diecast_high (die casting, high capacity): PASS

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 4 | 0.7 |
| 2 Part has a 3D file, revision A and geometry | ok | 2538 cm³, bbox {'length': 650.0, 'width': 450.0, 'height': 120.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.3 |
| 4 Tool and mould cost (BOM costed) | ok | tool cost INR 0, cavities None | 0.4 |
| 5 Design pack: Excel, PDF, PPT, 3D report, drawings, STEP | ok | 11 files, 18 s | 18.0 |
| 6 Generate the production tool design | ok | {'id': 4, 'part_id': 4, 'version': 1, 'rev_label': 'A', 'status': 'draft', 'kind': 'mould', 'part_type': 'die_casting', 'country': 'IN', 'as_of': '2026-10', 'summary': {'mould_base': '100120', 'base_m | 646.8 |
| 7 Tool design: no overlaps, valid solids | ok | 10 made parts, 289 standard 3D parts | 0.0 |
| 8 BOM: made parts with stock, weight, machining; bought-out list | ok | 9 part numbers, 6 bought-out lines, 11246.5 kg steel | 0.0 |
| 9 Tool part drawings (PDF, DXF) and STEP of every made part | ok | 9 part numbers: PDF + DXF + STEP each | 114.0 |
| 10 Downloaded STEP opens again as a valid solid | ok | DIECAST_HIGH-M-01 re-imports, 226406 cm³ | 0.1 |
| 10b Machine: recommended parameters of the finished tool | ok | machine not typed: the tool needs rec_tonnage_t = 3090 | 0.0 |
| 10c Process parameters for the best part quality | ok | 10 settings, 1 quality warning(s) | 4.6 |
| 11 3D viewer data (measure / view) | ok | 300 components for the 3D viewer | 14.3 |
| 12 Correct a component by STEP upload (round trip) | ok | revision B after upload, recalculated | 47.3 |
| 13 Toolmaker review signed | ok | 16 review items signed | 0.1 |
| 14 Release the design (drawing revision A) | ok | released | 45.2 |
| 15 Purchase orders: raw material, machining, bought-out (Excel + PDF) | ok | workbook 12 sheets, PO-1 9 lines, 3 PO PDFs + assembly sheet | 20.8 |
| 16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly) | ok | 34 files, 3576 KB | 140.7 |

## foundry_low (foundry, low capacity): PASS

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 5 | 0.2 |
| 2 Part has a 3D file, revision A and geometry | ok | 234 cm³, bbox {'length': 120.0, 'width': 80.0, 'height': 50.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.1 |
| 6 Generate the production tool design | ok | {'id': 5, 'part_id': 5, 'version': 1, 'rev_label': 'A', 'status': 'draft', 'kind': 'foundry', 'part_type': 'foundry', 'country': 'IN', 'as_of': '2026-10', 'summary': {'notes': 'Pattern: cope half is t | 3.5 |
| 7 Tool design: no overlaps, valid solids | ok | 9 made parts, 0 standard 3D parts | 0.0 |
| 8 BOM: made parts with stock, weight, machining; bought-out list | ok | 9 part numbers, 1 bought-out lines, 10.7 kg steel | 0.0 |
| 9 Tool part drawings (PDF, DXF) and STEP of every made part | ok | 9 part numbers: PDF + DXF + STEP each | 2.3 |
| 10 Downloaded STEP opens again as a valid solid | ok | FOUNDRY_LOW-F-01 re-imports, 259 cm³ | 0.1 |
| 10b Machine: recommended parameters of the finished tool | ok | machine not typed: the tool needs rec_flask_l_mm = 400 | 0.0 |
| 10c Process parameters for the best part quality | ok | 6 settings, 0 quality warning(s) | 0.1 |
| 11 3D viewer data (measure / view) | ok | 13 components for the 3D viewer | 0.2 |
| 12 Correct a component by STEP upload (round trip) | ok | revision B after upload, recalculated | 0.7 |
| 13 Toolmaker review signed | ok | 7 review items signed | 0.0 |
| 14 Release the design (drawing revision A) | ok | released | 0.4 |
| 15 Purchase orders: raw material, machining, bought-out (Excel + PDF) | ok | workbook 12 sheets, PO-1 9 lines, 3 PO PDFs + assembly sheet | 0.7 |
| 16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly) | ok | 34 files, 446 KB | 2.5 |

## foundry_high (foundry, high capacity): PASS

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 6 | 0.2 |
| 2 Part has a 3D file, revision A and geometry | ok | 19932 cm³, bbox {'length': 700.0, 'width': 450.0, 'height': 250.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.1 |
| 6 Generate the production tool design | ok | {'id': 6, 'part_id': 6, 'version': 1, 'rev_label': 'A', 'status': 'draft', 'kind': 'foundry', 'part_type': 'foundry', 'country': 'IN', 'as_of': '2026-10', 'summary': {'notes': 'Pattern: cope half is t | 7.8 |
| 7 Tool design: no overlaps, valid solids | ok | 10 made parts, 6 standard 3D parts | 0.0 |
| 8 BOM: made parts with stock, weight, machining; bought-out list | ok | 10 part numbers, 3 bought-out lines, 395.9 kg steel | 0.0 |
| 9 Tool part drawings (PDF, DXF) and STEP of every made part | ok | 10 part numbers: PDF + DXF + STEP each | 2.3 |
| 10 Downloaded STEP opens again as a valid solid | ok | FOUNDRY_HIGH-F-01 re-imports, 592 cm³ | 0.1 |
| 10b Machine: recommended parameters of the finished tool | ok | machine not typed: the tool needs rec_flask_l_mm = 1200 | 0.0 |
| 10c Process parameters for the best part quality | ok | 6 settings, 1 quality warning(s) | 0.1 |
| 11 3D viewer data (measure / view) | ok | 20 components for the 3D viewer | 0.3 |
| 12 Correct a component by STEP upload (round trip) | ok | revision B after upload, recalculated | 1.5 |
| 13 Toolmaker review signed | ok | 7 review items signed | 0.0 |
| 14 Release the design (drawing revision A) | ok | released | 1.3 |
| 15 Purchase orders: raw material, machining, bought-out (Excel + PDF) | ok | workbook 12 sheets, PO-1 10 lines, 3 PO PDFs + assembly sheet | 0.9 |
| 16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly) | ok | 37 files, 734 KB | 3.0 |

## sheet_progressive_low (sheet metal progressive, low capacity): PASS

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 7 | 0.2 |
| 2 Part has a 3D file, revision A and geometry | ok | 4 cm³, bbox {'length': 60.0, 'width': 30.0, 'height': 20.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.1 |
| 5 Design pack: Excel, PDF, PPT, 3D report, drawings, STEP | ok | 14 files, 5 s | 5.2 |
| 6 Generate the production tool design | ok | {'id': 7, 'part_id': 7, 'version': 1, 'rev_label': 'A', 'status': 'draft', 'kind': 'sheet_metal', 'part_type': 'sheet_metal', 'country': 'IN', 'as_of': '2026-10', 'summary': {'fea': {'available': True | 8.9 |
| 7 Tool design: no overlaps, valid solids | ok | 9 made parts, 35 standard 3D parts | 0.0 |
| 8 BOM: made parts with stock, weight, machining; bought-out list | ok | 8 part numbers, 6 bought-out lines, 88.0 kg steel | 0.0 |
| 9 Tool part drawings (PDF, DXF) and STEP of every made part | ok | 8 part numbers: PDF + DXF + STEP each | 1.9 |
| 10 Downloaded STEP opens again as a valid solid | ok | SHEET_PROGRESSIVE_LOW-P-01 re-imports, 814 cm³ | 0.1 |
| 10b Machine: recommended parameters of the finished tool | ok | machine not typed: the tool needs rec_tonnage_t = 20; closest Mechanical / servo press 63 t | 0.0 |
| 10c Process parameters for the best part quality | ok | 6 settings, 0 quality warning(s) | 0.5 |
| 11 3D viewer data (measure / view) | ok | 46 components for the 3D viewer | 0.9 |
| 12 Correct a component by STEP upload (round trip) | ok | revision B after upload, recalculated | 2.0 |
| 13 Toolmaker review signed | ok | 12 review items signed | 0.1 |
| 14 Release the design (drawing revision A) | ok | released | 1.4 |
| 15 Purchase orders: raw material, machining, bought-out (Excel + PDF) | ok | workbook 12 sheets, PO-1 8 lines, 3 PO PDFs + assembly sheet | 1.9 |
| 16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly) | ok | 31 files, 676 KB | 3.8 |
| 17 Progressive vs stage comparison and package | ok | Progressive die cheaper by INR 0.907; package 1649 KB | 34.3 |

## sheet_stage_low (sheet metal stage, low capacity): PASS

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 8 | 0.2 |
| 2 Part has a 3D file, revision A and geometry | ok | 4 cm³, bbox {'length': 60.0, 'width': 30.0, 'height': 20.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.1 |
| 5 Design pack: Excel, PDF, PPT, 3D report, drawings, STEP | ok | 15 files, 4 s | 4.1 |
| 6 Generate the production tool design | ok | {'id': 10, 'part_id': 8, 'version': 1, 'rev_label': 'A', 'status': 'draft', 'kind': 'sheet_metal', 'part_type': 'sheet_metal', 'country': 'IN', 'as_of': '2026-10', 'summary': {'fea': {'available': Tru | 11.9 |
| 7 Tool design: no overlaps, valid solids | ok | 15 made parts, 60 standard 3D parts | 0.0 |
| 8 BOM: made parts with stock, weight, machining; bought-out list | ok | 14 part numbers, 7 bought-out lines, 118.2 kg steel | 0.0 |
| 9 Tool part drawings (PDF, DXF) and STEP of every made part | ok | 14 part numbers: PDF + DXF + STEP each | 3.5 |
| 10 Downloaded STEP opens again as a valid solid | ok | SHEET_STAGE_LOW-S1-01 re-imports, 475 cm³ | 0.1 |
| 10b Machine: recommended parameters of the finished tool | ok | machine not typed: the tool needs rec_tonnage_t = 20; closest Mechanical / servo press 63 t | 0.0 |
| 10c Process parameters for the best part quality | ok | 6 settings, 0 quality warning(s) | 0.5 |
| 11 3D viewer data (measure / view) | ok | 77 components for the 3D viewer | 1.2 |
| 12 Correct a component by STEP upload (round trip) | ok | revision B after upload, recalculated | 2.7 |
| 13 Toolmaker review signed | ok | 12 review items signed | 0.1 |
| 14 Release the design (drawing revision A) | ok | released | 2.2 |
| 15 Purchase orders: raw material, machining, bought-out (Excel + PDF) | ok | workbook 12 sheets, PO-1 14 lines, 3 PO PDFs + assembly sheet | 2.4 |
| 16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly) | ok | 49 files, 943 KB | 5.9 |
| 17 Progressive vs stage comparison and package | ok | Progressive die cheaper by INR 0.907; package 1647 KB | 34.8 |

## sheet_progressive_high (sheet metal progressive, high capacity): PASS

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 9 | 0.1 |
| 2 Part has a 3D file, revision A and geometry | ok | 366 cm³, bbox {'length': 500.0, 'width': 250.0, 'height': 60.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.1 |
| 5 Design pack: Excel, PDF, PPT, 3D report, drawings, STEP | ok | 14 files, 6 s | 5.9 |
| 6 Generate the production tool design | ok | {'id': 13, 'part_id': 9, 'version': 1, 'rev_label': 'A', 'status': 'draft', 'kind': 'sheet_metal', 'part_type': 'sheet_metal', 'country': 'IN', 'as_of': '2026-10', 'summary': {'fea': {'available': Tru | 27.7 |
| 7 Tool design: no overlaps, valid solids | ok | 10 made parts, 82 standard 3D parts | 0.0 |
| 8 BOM: made parts with stock, weight, machining; bought-out list | ok | 9 part numbers, 6 bought-out lines, 2071.8 kg steel | 0.0 |
| 9 Tool part drawings (PDF, DXF) and STEP of every made part | ok | 9 part numbers: PDF + DXF + STEP each | 4.4 |
| 10 Downloaded STEP opens again as a valid solid | ok | SHEET_PROGRESSIVE_HIGH-P-01 re-imports, 26499 cm³ | 0.2 |
| 10b Machine: recommended parameters of the finished tool | ok | machine not typed: the tool needs rec_tonnage_t = 190; closest Power press 200 t | 0.0 |
| 10c Process parameters for the best part quality | ok | 6 settings, 1 quality warning(s) | 0.5 |
| 11 3D viewer data (measure / view) | ok | 94 components for the 3D viewer | 2.2 |
| 12 Correct a component by STEP upload (round trip) | ok | revision B after upload, recalculated | 5.7 |
| 13 Toolmaker review signed | ok | 12 review items signed | 0.1 |
| 14 Release the design (drawing revision A) | ok | released | 5.2 |
| 15 Purchase orders: raw material, machining, bought-out (Excel + PDF) | ok | workbook 12 sheets, PO-1 9 lines, 3 PO PDFs + assembly sheet | 3.6 |
| 16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly) | ok | 34 files, 1238 KB | 8.3 |
| 17 Progressive vs stage comparison and package | ok | Progressive die cheaper by INR 46.588; package 3175 KB | 95.1 |

## sheet_stage_high (sheet metal stage, high capacity): PASS

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 10 | 0.2 |
| 2 Part has a 3D file, revision A and geometry | ok | 366 cm³, bbox {'length': 500.0, 'width': 250.0, 'height': 60.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.1 |
| 5 Design pack: Excel, PDF, PPT, 3D report, drawings, STEP | ok | 15 files, 5 s | 5.0 |
| 6 Generate the production tool design | ok | {'id': 16, 'part_id': 10, 'version': 1, 'rev_label': 'A', 'status': 'draft', 'kind': 'sheet_metal', 'part_type': 'sheet_metal', 'country': 'IN', 'as_of': '2026-10', 'summary': {'fea': {'available': Tr | 35.6 |
| 7 Tool design: no overlaps, valid solids | ok | 16 made parts, 144 standard 3D parts | 0.0 |
| 8 BOM: made parts with stock, weight, machining; bought-out list | ok | 15 part numbers, 7 bought-out lines, 1504.4 kg steel | 0.0 |
| 9 Tool part drawings (PDF, DXF) and STEP of every made part | ok | 15 part numbers: PDF + DXF + STEP each | 8.4 |
| 10 Downloaded STEP opens again as a valid solid | ok | SHEET_STAGE_HIGH-S1-01 re-imports, 5676 cm³ | 0.2 |
| 10b Machine: recommended parameters of the finished tool | ok | machine not typed: the tool needs rec_tonnage_t = 170; closest Power press 200 t | 0.0 |
| 10c Process parameters for the best part quality | ok | 6 settings, 0 quality warning(s) | 0.5 |
| 11 3D viewer data (measure / view) | ok | 162 components for the 3D viewer | 5.2 |
| 12 Correct a component by STEP upload (round trip) | ok | revision B after upload, recalculated | 10.7 |
| 13 Toolmaker review signed | ok | 12 review items signed | 0.1 |
| 14 Release the design (drawing revision A) | ok | released | 6.7 |
| 15 Purchase orders: raw material, machining, bought-out (Excel + PDF) | ok | workbook 12 sheets, PO-1 15 lines, 3 PO PDFs + assembly sheet | 7.4 |
| 16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly) | ok | 52 files, 1906 KB | 14.2 |
| 17 Progressive vs stage comparison and package | ok | Progressive die cheaper by INR 46.588; package 3173 KB | 96.9 |

## eps_low (EPS, low capacity): PASS

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 11 | 0.6 |
| 2 Part has a 3D file, revision A and geometry | ok | 1086 cm³, bbox {'length': 200.0, 'width': 150.0, 'height': 80.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.3 |
| 4 Tool and mould cost (BOM costed) | ok | tool cost INR 0, cavities None | 0.4 |
| 6 Generate the production tool design | ok | {'id': 19, 'part_id': 11, 'version': 1, 'rev_label': 'A', 'status': 'draft', 'kind': 'mould', 'part_type': 'eps', 'country': 'IN', 'as_of': '2026-10', 'summary': {'mould_base': '0806', 'base_mm': [800 | 95.5 |
| 7 Tool design: no overlaps, valid solids | ok | 4 made parts, 42 standard 3D parts | 0.0 |
| 8 BOM: made parts with stock, weight, machining; bought-out list | ok | 4 part numbers, 7 bought-out lines, 1782.6 kg steel | 0.0 |
| 9 Tool part drawings (PDF, DXF) and STEP of every made part | ok | 4 part numbers: PDF + DXF + STEP each | 1.6 |
| 10 Downloaded STEP opens again as a valid solid | ok | EPS_LOW-M-01 re-imports, 72545 cm³ | 0.1 |
| 10b Machine: recommended parameters of the finished tool | ok | machine not typed: the tool needs rec_tonnage_t = 10; closest EPS shape moulding machine 1000 x 800 | 0.0 |
| 10c Process parameters for the best part quality | ok | 4 settings, 0 quality warning(s) | 0.1 |
| 11 3D viewer data (measure / view) | ok | 47 components for the 3D viewer | 0.9 |
| 12 Correct a component by STEP upload (round trip) | ok | revision B after upload, recalculated | 1.6 |
| 13 Toolmaker review signed | ok | 16 review items signed | 0.1 |
| 14 Release the design (drawing revision A) | ok | released | 1.2 |
| 15 Purchase orders: raw material, machining, bought-out (Excel + PDF) | ok | workbook 12 sheets, PO-1 4 lines, 3 PO PDFs + assembly sheet | 1.9 |
| 16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly) | ok | 19 files, 519 KB | 3.4 |

## eps_high (EPS, high capacity): PASS

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 12 | 0.6 |
| 2 Part has a 3D file, revision A and geometry | ok | 52293 cm³, bbox {'length': 1000.0, 'width': 600.0, 'height': 400.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.3 |
| 4 Tool and mould cost (BOM costed) | ok | tool cost INR 0, cavities None | 0.5 |
| 6 Generate the production tool design | ok | {'id': 20, 'part_id': 12, 'version': 1, 'rev_label': 'A', 'status': 'draft', 'kind': 'mould', 'part_type': 'eps', 'country': 'IN', 'as_of': '2026-10', 'summary': {'mould_base': '1412', 'base_mm': [140 | 97.0 |
| 7 Tool design: no overlaps, valid solids | ok | 4 made parts, 38 standard 3D parts | 0.0 |
| 8 BOM: made parts with stock, weight, machining; bought-out list | ok | 4 part numbers, 7 bought-out lines, 7275.8 kg steel | 0.0 |
| 9 Tool part drawings (PDF, DXF) and STEP of every made part | ok | 4 part numbers: PDF + DXF + STEP each | 164.1 |
| 10 Downloaded STEP opens again as a valid solid | ok | EPS_HIGH-M-01 re-imports, 209622 cm³ | 0.1 |
| 10b Machine: recommended parameters of the finished tool | ok | machine not typed: the tool needs rec_tonnage_t = 20; closest EPS shape moulding machine 1000 x 800 | 0.0 |
| 10c Process parameters for the best part quality | ok | 4 settings, 0 quality warning(s) | 0.1 |
| 11 3D viewer data (measure / view) | ok | 43 components for the 3D viewer | 1.1 |
| 12 Correct a component by STEP upload (round trip) | ok | revision B after upload, recalculated | 2.0 |
| 13 Toolmaker review signed | ok | 16 review items signed | 0.1 |
| 14 Release the design (drawing revision A) | ok | released | 1.8 |
| 15 Purchase orders: raw material, machining, bought-out (Excel + PDF) | ok | workbook 12 sheets, PO-1 4 lines, 3 PO PDFs + assembly sheet | 1.6 |
| 16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly) | ok | 19 files, 1265 KB | 155.9 |

## blow_low (blow, low capacity): PASS

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 13 | 0.5 |
| 2 Part has a 3D file, revision A and geometry | ok | 17 cm³, bbox {'length': 150.0, 'width': 60.0, 'height': 60.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.4 |
| 4 Tool and mould cost (BOM costed) | ok | tool cost INR 0, cavities None | 0.5 |
| 6 Generate the production tool design | ok | {'id': 21, 'part_id': 13, 'version': 1, 'rev_label': 'A', 'status': 'draft', 'kind': 'mould', 'part_type': 'blow', 'country': 'IN', 'as_of': '2026-10', 'summary': {'mould_base': '7015', 'base_mm': [70 | 15.2 |
| 7 Tool design: no overlaps, valid solids | ok | 4 made parts, 26 standard 3D parts | 0.0 |
| 8 BOM: made parts with stock, weight, machining; bought-out list | ok | 4 part numbers, 6 bought-out lines, 133.5 kg steel | 0.0 |
| 9 Tool part drawings (PDF, DXF) and STEP of every made part | ok | 4 part numbers: PDF + DXF + STEP each | 21.2 |
| 10 Downloaded STEP opens again as a valid solid | ok | BLOW_LOW-M-01 re-imports, 5012 cm³ | 0.0 |
| 10b Machine: recommended parameters of the finished tool | ok | machine not typed: the tool needs rec_tonnage_t = 10; closest Linear stretch blow machine 2 cavities | 0.0 |
| 10c Process parameters for the best part quality | ok | 5 settings, 0 quality warning(s) | 0.1 |
| 11 3D viewer data (measure / view) | ok | 31 components for the 3D viewer | 0.5 |
| 12 Correct a component by STEP upload (round trip) | ok | revision B after upload, recalculated | 2.2 |
| 13 Toolmaker review signed | ok | 16 review items signed | 0.1 |
| 14 Release the design (drawing revision A) | ok | released | 1.8 |
| 15 Purchase orders: raw material, machining, bought-out (Excel + PDF) | ok | workbook 12 sheets, PO-1 4 lines, 3 PO PDFs + assembly sheet | 1.3 |
| 16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly) | ok | 19 files, 789 KB | 22.1 |

## blow_high (blow, high capacity): PASS

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 14 | 0.5 |
| 2 Part has a 3D file, revision A and geometry | ok | 211 cm³, bbox {'length': 300.0, 'width': 150.0, 'height': 150.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.3 |
| 4 Tool and mould cost (BOM costed) | ok | tool cost INR 0, cavities None | 0.4 |
| 6 Generate the production tool design | ok | {'id': 22, 'part_id': 14, 'version': 1, 'rev_label': 'A', 'status': 'draft', 'kind': 'mould', 'part_type': 'blow', 'country': 'IN', 'as_of': '2026-10', 'summary': {'mould_base': '6030', 'base_mm': [60 | 35.3 |
| 7 Tool design: no overlaps, valid solids | ok | 4 made parts, 34 standard 3D parts | 0.0 |
| 8 BOM: made parts with stock, weight, machining; bought-out list | ok | 4 part numbers, 6 bought-out lines, 353.0 kg steel | 0.0 |
| 9 Tool part drawings (PDF, DXF) and STEP of every made part | ok | 4 part numbers: PDF + DXF + STEP each | 37.9 |
| 10 Downloaded STEP opens again as a valid solid | ok | BLOW_HIGH-M-01 re-imports, 10813 cm³ | 0.1 |
| 10b Machine: recommended parameters of the finished tool | ok | machine not typed: the tool needs rec_tonnage_t = 20; closest Linear stretch blow machine 4 cavities | 0.0 |
| 10c Process parameters for the best part quality | ok | 5 settings, 0 quality warning(s) | 0.1 |
| 11 3D viewer data (measure / view) | ok | 39 components for the 3D viewer | 0.7 |
| 12 Correct a component by STEP upload (round trip) | ok | revision B after upload, recalculated | 2.7 |
| 13 Toolmaker review signed | ok | 16 review items signed | 0.1 |
| 14 Release the design (drawing revision A) | ok | released | 2.3 |
| 15 Purchase orders: raw material, machining, bought-out (Excel + PDF) | ok | workbook 12 sheets, PO-1 4 lines, 3 PO PDFs + assembly sheet | 1.3 |
| 16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly) | ok | 19 files, 1042 KB | 39.3 |
