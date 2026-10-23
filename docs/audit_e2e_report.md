# End-to-end audit: every tool group, low and high capacity

Run on 2026-10-23 with `python scripts/audit_e2e.py` (sample parts in `samples/audit/`, made by `samples/make_audit_samples.py`).
Each case goes from 3D upload to the supplier ZIP; every file is downloaded and opened again. Example rates and rules are still EXAMPLE values.

**5 of 14 cases passed all steps.**

| Case | Group | Capacity | Result | Made parts | 3D standard parts | Force (t) | Press / base | Steel (kg) | Seconds |
|---|---|---|---|---|---|---|---|---|---|
| plastic_low | plastic | low | PASS | 10 | 47 |  | - | 136.2 | 112 |
| plastic_high | plastic | high | FAIL |  |  |  |  |  |  |
| diecast_low | die casting | low | PASS | 10 | 61 |  | - | 827.6 | 114 |
| diecast_high | die casting | high | FAIL |  |  |  |  |  |  |
| foundry_low | foundry | low | PASS | 9 | 0 |  | - | 10.7 | 8 |
| foundry_high | foundry | high | FAIL | 10 | 6 |  | - | 395.9 | 12 |
| sheet_progressive_low | sheet metal progressive | low | PASS | 9 | 36 | 11.4 | Mechanical / servo press 63 t | 88.0 | 48 |
| sheet_stage_low | sheet metal stage | low | PASS | 15 | 63 | 11.4 | Mechanical / servo press 63 t | 118.2 | 57 |
| sheet_progressive_high | sheet metal progressive | high | FAIL |  |  |  |  |  |  |
| sheet_stage_high | sheet metal stage | high | FAIL |  |  |  |  |  |  |
| eps_low | EPS | low | FAIL | 4 | 42 |  | - | 1782.6 | 83 |
| eps_high | EPS | high | FAIL | 4 | 38 |  | - | 7275.8 | 323 |
| blow_low | blow | low | FAIL | 4 | 26 |  | - | 133.5 | 51 |
| blow_high | blow | high | FAIL | 4 | 34 |  | - | 353.0 | 99 |

## plastic_low (plastic, low capacity): PASS

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 1 | 4.0 |
| 2 Part has a 3D file, revision A and geometry | ok | 19 cm³, bbox {'length': 80.0, 'width': 50.0, 'height': 20.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.3 |
| 4 Tool and mould cost (BOM costed) | ok | tool cost INR 0, cavities None | 0.4 |
| 5 Design pack: Excel, PDF, PPT, 3D report, drawings, STEP | ok | 11 files, 36 s | 36.2 |
| 6 Generate the production tool design | ok | {'id': 1, 'part_id': 1, 'version': 1, 'rev_label': 'A', 'status': 'draft', 'kind': 'mould', 'part_type': 'plastic', 'country': 'IN', 'as_of': '2026-10', 'summary': {'mould_base': '2025', 'cavities': 1 | 35.3 |
| 7 Tool design: no overlaps, valid solids | ok | 10 made parts, 47 standard 3D parts | 0.0 |
| 8 BOM: made parts with stock, weight, machining; bought-out list | ok | 9 part numbers, 10 bought-out lines, 136.2 kg steel | 0.0 |
| 9 Tool part drawings (PDF, DXF) and STEP of every made part | ok | 9 part numbers: PDF + DXF + STEP each | 12.6 |
| 10 Downloaded STEP opens again as a valid solid | ok | PLASTIC_LOW-M-01 re-imports, 1942 cm³ | 0.0 |
| 11 3D viewer data (measure / view) | ok | 58 components for the 3D viewer | 0.8 |
| 12 Correct a component by STEP upload (round trip) | ok | revision B after upload, recalculated | 2.0 |
| 13 Toolmaker review signed | ok | 14 review items signed | 0.1 |
| 14 Release the design (drawing revision A) | ok | released | 1.7 |
| 15 Purchase orders: raw material, machining, bought-out (Excel + PDF) | ok | workbook 11 sheets, PO-1 9 lines, 3 PO PDFs + assembly sheet | 1.9 |
| 16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly) | ok | 34 files, 885 KB | 15.8 |

## plastic_high (plastic, high capacity): FAIL

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 2 | 0.6 |
| 2 Part has a 3D file, revision A and geometry | ok | 4336 cm³, bbox {'length': 1100.0, 'width': 600.0, 'height': 180.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.1 |
| 4 Tool and mould cost (BOM costed) | **FAILED** | AssertionError: {"detail":"Stage C (cavities and tools) cannot be worked out: The part does not fit on the tool plate. Check the plate size and spacing."} | 0.0 |
| 5 Design pack: Excel, PDF, PPT, 3D report, drawings, STEP | **FAILED** | AssertionError: {"detail":"Stage C (cavities and tools) cannot be worked out: The part does not fit on the tool plate. Check the plate size and spacing."} | 8.3 |
| 6 Generate the production tool design | **FAILED** | AssertionError: {"detail":"Stage C (cavities and tools) cannot be worked out: The part does not fit on the tool plate. Check the plate size and spacing."} | 8.5 |

## diecast_low (die casting, low capacity): PASS

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 3 | 0.6 |
| 2 Part has a 3D file, revision A and geometry | ok | 24 cm³, bbox {'length': 70.0, 'width': 50.0, 'height': 25.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.3 |
| 4 Tool and mould cost (BOM costed) | ok | tool cost INR 0, cavities None | 0.4 |
| 5 Design pack: Excel, PDF, PPT, 3D report, drawings, STEP | ok | 11 files, 12 s | 11.9 |
| 6 Generate the production tool design | ok | {'id': 2, 'part_id': 3, 'version': 1, 'rev_label': 'A', 'status': 'draft', 'kind': 'mould', 'part_type': 'die_casting', 'country': 'IN', 'as_of': '2026-10', 'summary': {'mould_base': '4040', 'cavities | 47.9 |
| 7 Tool design: no overlaps, valid solids | ok | 10 made parts, 61 standard 3D parts | 0.0 |
| 8 BOM: made parts with stock, weight, machining; bought-out list | ok | 9 part numbers, 6 bought-out lines, 827.6 kg steel | 0.0 |
| 9 Tool part drawings (PDF, DXF) and STEP of every made part | ok | 9 part numbers: PDF + DXF + STEP each | 22.5 |
| 10 Downloaded STEP opens again as a valid solid | ok | DIECAST_LOW-M-01 re-imports, 18579 cm³ | 0.1 |
| 11 3D viewer data (measure / view) | ok | 72 components for the 3D viewer | 1.1 |
| 12 Correct a component by STEP upload (round trip) | ok | revision B after upload, recalculated | 2.4 |
| 13 Toolmaker review signed | ok | 14 review items signed | 0.1 |
| 14 Release the design (drawing revision A) | ok | released | 2.1 |
| 15 Purchase orders: raw material, machining, bought-out (Excel + PDF) | ok | workbook 11 sheets, PO-1 9 lines, 3 PO PDFs + assembly sheet | 1.7 |
| 16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly) | ok | 34 files, 982 KB | 22.6 |

## diecast_high (die casting, high capacity): FAIL

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 4 | 0.5 |
| 2 Part has a 3D file, revision A and geometry | ok | 2538 cm³, bbox {'length': 650.0, 'width': 450.0, 'height': 120.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.1 |
| 4 Tool and mould cost (BOM costed) | **FAILED** | AssertionError: {"detail":"Stage C (cavities and tools) cannot be worked out: The part does not fit on the tool plate. Check the plate size and spacing."} | 0.0 |
| 5 Design pack: Excel, PDF, PPT, 3D report, drawings, STEP | **FAILED** | AssertionError: {"detail":"Stage C (cavities and tools) cannot be worked out: The part does not fit on the tool plate. Check the plate size and spacing."} | 6.8 |
| 6 Generate the production tool design | **FAILED** | AssertionError: {"detail":"Stage C (cavities and tools) cannot be worked out: The part does not fit on the tool plate. Check the plate size and spacing."} | 7.3 |

## foundry_low (foundry, low capacity): PASS

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 5 | 0.2 |
| 2 Part has a 3D file, revision A and geometry | ok | 234 cm³, bbox {'length': 120.0, 'width': 80.0, 'height': 50.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.1 |
| 6 Generate the production tool design | ok | {'id': 3, 'part_id': 5, 'version': 1, 'rev_label': 'A', 'status': 'draft', 'kind': 'foundry', 'part_type': 'foundry', 'country': 'IN', 'as_of': '2026-10', 'summary': {'notes': 'Pattern: cope half is t | 2.6 |
| 7 Tool design: no overlaps, valid solids | ok | 9 made parts, 0 standard 3D parts | 0.0 |
| 8 BOM: made parts with stock, weight, machining; bought-out list | ok | 8 part numbers, 1 bought-out lines, 10.7 kg steel | 0.0 |
| 9 Tool part drawings (PDF, DXF) and STEP of every made part | ok | 8 part numbers: PDF + DXF + STEP each | 1.5 |
| 10 Downloaded STEP opens again as a valid solid | ok | FOUNDRY_LOW-F-01 re-imports, 259 cm³ | 0.0 |
| 11 3D viewer data (measure / view) | ok | 13 components for the 3D viewer | 0.2 |
| 12 Correct a component by STEP upload (round trip) | ok | revision B after upload, recalculated | 0.5 |
| 13 Toolmaker review signed | ok | 6 review items signed | 0.0 |
| 14 Release the design (drawing revision A) | ok | released | 0.3 |
| 15 Purchase orders: raw material, machining, bought-out (Excel + PDF) | ok | workbook 11 sheets, PO-1 8 lines, 3 PO PDFs + assembly sheet | 0.6 |
| 16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly) | ok | 31 files, 427 KB | 1.8 |

## foundry_high (foundry, high capacity): FAIL

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 6 | 0.1 |
| 2 Part has a 3D file, revision A and geometry | ok | 19932 cm³, bbox {'length': 700.0, 'width': 450.0, 'height': 250.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.1 |
| 6 Generate the production tool design | ok | {'id': 4, 'part_id': 6, 'version': 1, 'rev_label': 'A', 'status': 'draft', 'kind': 'foundry', 'part_type': 'foundry', 'country': 'IN', 'as_of': '2026-10', 'summary': {'notes': 'Pattern: cope half is t | 5.5 |
| 7 Tool design: no overlaps, valid solids | ok | 10 made parts, 6 standard 3D parts | 0.0 |
| 8 BOM: made parts with stock, weight, machining; bought-out list | ok | 8 part numbers, 3 bought-out lines, 395.9 kg steel | 0.0 |
| 9 Tool part drawings (PDF, DXF) and STEP of every made part | ok | 8 part numbers: PDF + DXF + STEP each | 1.2 |
| 10 Downloaded STEP opens again as a valid solid | ok | FOUNDRY_HIGH-F-01 re-imports, 592 cm³ | 0.0 |
| 11 3D viewer data (measure / view) | ok | 20 components for the 3D viewer | 0.3 |
| 12 Correct a component by STEP upload (round trip) | ok | revision B after upload, recalculated | 1.3 |
| 13 Toolmaker review signed | ok | 6 review items signed | 0.1 |
| 14 Release the design (drawing revision A) | **FAILED** | AssertionError: not released | 0.8 |
| 15 Purchase orders: raw material, machining, bought-out (Excel + PDF) | ok | workbook 11 sheets, PO-1 8 lines, 3 PO PDFs + assembly sheet | 0.7 |
| 16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly) | ok | 31 files, 632 KB | 2.2 |

## sheet_progressive_low (sheet metal progressive, low capacity): PASS

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 7 | 0.1 |
| 2 Part has a 3D file, revision A and geometry | ok | 4 cm³, bbox {'length': 60.0, 'width': 30.0, 'height': 20.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.1 |
| 5 Design pack: Excel, PDF, PPT, 3D report, drawings, STEP | ok | 14 files, 3 s | 3.4 |
| 6 Generate the production tool design | ok | {'id': 5, 'part_id': 7, 'version': 1, 'rev_label': 'A', 'status': 'draft', 'kind': 'sheet_metal', 'part_type': 'sheet_metal', 'country': 'IN', 'as_of': '2026-10', 'summary': {'fea': {'available': True | 7.5 |
| 7 Tool design: no overlaps, valid solids | ok | 9 made parts, 36 standard 3D parts | 0.0 |
| 8 BOM: made parts with stock, weight, machining; bought-out list | ok | 8 part numbers, 6 bought-out lines, 88.0 kg steel | 0.0 |
| 9 Tool part drawings (PDF, DXF) and STEP of every made part | ok | 8 part numbers: PDF + DXF + STEP each | 1.6 |
| 10 Downloaded STEP opens again as a valid solid | ok | SHEET_PROGRESS-P-01 re-imports, 814 cm³ | 0.1 |
| 11 3D viewer data (measure / view) | ok | 47 components for the 3D viewer | 0.6 |
| 12 Correct a component by STEP upload (round trip) | ok | revision B after upload, recalculated | 1.4 |
| 13 Toolmaker review signed | ok | 10 review items signed | 0.1 |
| 14 Release the design (drawing revision A) | ok | released | 1.2 |
| 15 Purchase orders: raw material, machining, bought-out (Excel + PDF) | ok | workbook 11 sheets, PO-1 8 lines, 3 PO PDFs + assembly sheet | 1.4 |
| 16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly) | ok | 31 files, 677 KB | 2.9 |
| 17 Progressive vs stage comparison and package | ok | Progressive die cheaper by INR 0.908; package 1659 KB | 27.3 |

## sheet_stage_low (sheet metal stage, low capacity): PASS

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 8 | 0.2 |
| 2 Part has a 3D file, revision A and geometry | ok | 4 cm³, bbox {'length': 60.0, 'width': 30.0, 'height': 20.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.1 |
| 5 Design pack: Excel, PDF, PPT, 3D report, drawings, STEP | ok | 15 files, 3 s | 3.3 |
| 6 Generate the production tool design | ok | {'id': 8, 'part_id': 8, 'version': 1, 'rev_label': 'A', 'status': 'draft', 'kind': 'sheet_metal', 'part_type': 'sheet_metal', 'country': 'IN', 'as_of': '2026-10', 'summary': {'fea': {'available': True | 9.9 |
| 7 Tool design: no overlaps, valid solids | ok | 15 made parts, 63 standard 3D parts | 0.0 |
| 8 BOM: made parts with stock, weight, machining; bought-out list | ok | 14 part numbers, 7 bought-out lines, 118.2 kg steel | 0.0 |
| 9 Tool part drawings (PDF, DXF) and STEP of every made part | ok | 14 part numbers: PDF + DXF + STEP each | 2.7 |
| 10 Downloaded STEP opens again as a valid solid | ok | SHEET_STAGE_LO-S1-01 re-imports, 475 cm³ | 0.0 |
| 11 3D viewer data (measure / view) | ok | 80 components for the 3D viewer | 1.0 |
| 12 Correct a component by STEP upload (round trip) | ok | revision B after upload, recalculated | 2.5 |
| 13 Toolmaker review signed | ok | 10 review items signed | 0.1 |
| 14 Release the design (drawing revision A) | ok | released | 2.0 |
| 15 Purchase orders: raw material, machining, bought-out (Excel + PDF) | ok | workbook 11 sheets, PO-1 14 lines, 3 PO PDFs + assembly sheet | 2.0 |
| 16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly) | ok | 49 files, 952 KB | 4.9 |
| 17 Progressive vs stage comparison and package | ok | Progressive die cheaper by INR 0.908; package 1659 KB | 28.8 |

## sheet_progressive_high (sheet metal progressive, high capacity): FAIL

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | **FAILED** | KeyError: 'id' | 0.1 |

## sheet_stage_high (sheet metal stage, high capacity): FAIL

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | **FAILED** | KeyError: 'id' | 0.1 |

## eps_low (EPS, low capacity): FAIL

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 9 | 0.6 |
| 2 Part has a 3D file, revision A and geometry | ok | 1086 cm³, bbox {'length': 200.0, 'width': 150.0, 'height': 80.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.2 |
| 4 Tool and mould cost (BOM costed) | ok | tool cost INR 0, cavities None | 0.4 |
| 5 Design pack: Excel, PDF, PPT, 3D report, drawings, STEP | **FAILED** | AssertionError: {"detail":"The design pack covers plastic moulds, die-casting dies and sheet-metal tools. EPS, blow and foundry parts: use the 3D tool design page (production tool design) of the part."} | 0.0 |
| 6 Generate the production tool design | ok | {'id': 11, 'part_id': 9, 'version': 1, 'rev_label': 'A', 'status': 'draft', 'kind': 'mould', 'part_type': 'eps', 'country': 'IN', 'as_of': '2026-10', 'summary': {'mould_base': '0806', 'cavities': 2, ' | 73.5 |
| 7 Tool design: no overlaps, valid solids | ok | 4 made parts, 42 standard 3D parts | 0.0 |
| 8 BOM: made parts with stock, weight, machining; bought-out list | ok | 4 part numbers, 7 bought-out lines, 1782.6 kg steel | 0.0 |
| 9 Tool part drawings (PDF, DXF) and STEP of every made part | ok | 4 part numbers: PDF + DXF + STEP each | 1.3 |
| 10 Downloaded STEP opens again as a valid solid | ok | EPS_LOW-M-01 re-imports, 72545 cm³ | 0.1 |
| 11 3D viewer data (measure / view) | ok | 47 components for the 3D viewer | 0.7 |
| 12 Correct a component by STEP upload (round trip) | ok | revision B after upload, recalculated | 1.4 |
| 13 Toolmaker review signed | ok | 14 review items signed | 0.1 |
| 14 Release the design (drawing revision A) | ok | released | 1.0 |
| 15 Purchase orders: raw material, machining, bought-out (Excel + PDF) | ok | workbook 11 sheets, PO-1 4 lines, 3 PO PDFs + assembly sheet | 1.4 |
| 16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly) | ok | 19 files, 518 KB | 2.6 |

## eps_high (EPS, high capacity): FAIL

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 10 | 0.5 |
| 2 Part has a 3D file, revision A and geometry | ok | 52293 cm³, bbox {'length': 1000.0, 'width': 600.0, 'height': 400.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.2 |
| 4 Tool and mould cost (BOM costed) | ok | tool cost INR 0, cavities None | 0.3 |
| 5 Design pack: Excel, PDF, PPT, 3D report, drawings, STEP | **FAILED** | AssertionError: {"detail":"The design pack covers plastic moulds, die-casting dies and sheet-metal tools. EPS, blow and foundry parts: use the 3D tool design page (production tool design) of the part."} | 0.0 |
| 6 Generate the production tool design | ok | {'id': 12, 'part_id': 10, 'version': 1, 'rev_label': 'A', 'status': 'draft', 'kind': 'mould', 'part_type': 'eps', 'country': 'IN', 'as_of': '2026-10', 'summary': {'mould_base': '1412', 'cavities': 1,  | 67.8 |
| 7 Tool design: no overlaps, valid solids | ok | 4 made parts, 38 standard 3D parts | 0.0 |
| 8 BOM: made parts with stock, weight, machining; bought-out list | ok | 4 part numbers, 7 bought-out lines, 7275.8 kg steel | 0.0 |
| 9 Tool part drawings (PDF, DXF) and STEP of every made part | ok | 4 part numbers: PDF + DXF + STEP each | 127.1 |
| 10 Downloaded STEP opens again as a valid solid | ok | EPS_HIGH-M-01 re-imports, 209622 cm³ | 0.0 |
| 11 3D viewer data (measure / view) | ok | 43 components for the 3D viewer | 0.7 |
| 12 Correct a component by STEP upload (round trip) | ok | revision B after upload, recalculated | 1.7 |
| 13 Toolmaker review signed | ok | 14 review items signed | 0.1 |
| 14 Release the design (drawing revision A) | ok | released | 1.5 |
| 15 Purchase orders: raw material, machining, bought-out (Excel + PDF) | ok | workbook 11 sheets, PO-1 4 lines, 3 PO PDFs + assembly sheet | 1.3 |
| 16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly) | ok | 19 files, 1264 KB | 121.5 |

## blow_low (blow, low capacity): FAIL

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 11 | 0.4 |
| 2 Part has a 3D file, revision A and geometry | ok | 17 cm³, bbox {'length': 150.0, 'width': 60.0, 'height': 60.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.2 |
| 4 Tool and mould cost (BOM costed) | ok | tool cost INR 0, cavities None | 0.5 |
| 5 Design pack: Excel, PDF, PPT, 3D report, drawings, STEP | **FAILED** | AssertionError: {"detail":"The design pack covers plastic moulds, die-casting dies and sheet-metal tools. EPS, blow and foundry parts: use the 3D tool design page (production tool design) of the part."} | 0.0 |
| 6 Generate the production tool design | ok | {'id': 13, 'part_id': 11, 'version': 1, 'rev_label': 'A', 'status': 'draft', 'kind': 'mould', 'part_type': 'blow', 'country': 'IN', 'as_of': '2026-10', 'summary': {'mould_base': '7015', 'cavities': 1, | 10.7 |
| 7 Tool design: no overlaps, valid solids | ok | 4 made parts, 26 standard 3D parts | 0.0 |
| 8 BOM: made parts with stock, weight, machining; bought-out list | ok | 4 part numbers, 6 bought-out lines, 133.5 kg steel | 0.0 |
| 9 Tool part drawings (PDF, DXF) and STEP of every made part | ok | 4 part numbers: PDF + DXF + STEP each | 17.5 |
| 10 Downloaded STEP opens again as a valid solid | ok | BLOW_LOW-M-01 re-imports, 5012 cm³ | 0.0 |
| 11 3D viewer data (measure / view) | ok | 31 components for the 3D viewer | 0.4 |
| 12 Correct a component by STEP upload (round trip) | ok | revision B after upload, recalculated | 1.5 |
| 13 Toolmaker review signed | ok | 14 review items signed | 0.1 |
| 14 Release the design (drawing revision A) | ok | released | 1.2 |
| 15 Purchase orders: raw material, machining, bought-out (Excel + PDF) | ok | workbook 11 sheets, PO-1 4 lines, 3 PO PDFs + assembly sheet | 0.9 |
| 16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly) | ok | 19 files, 788 KB | 17.7 |

## blow_high (blow, high capacity): FAIL

| Step | Result | Detail | s |
|---|---|---|---|
| 1 Upload 3D drawing and register the part | ok | 12 | 0.4 |
| 2 Part has a 3D file, revision A and geometry | ok | 211 cm³, bbox {'length': 300.0, 'width': 150.0, 'height': 150.0} | 0.0 |
| 3 Raw-material cost | ok | RM cost INR None | 0.2 |
| 4 Tool and mould cost (BOM costed) | ok | tool cost INR 0, cavities None | 0.3 |
| 5 Design pack: Excel, PDF, PPT, 3D report, drawings, STEP | **FAILED** | AssertionError: {"detail":"The design pack covers plastic moulds, die-casting dies and sheet-metal tools. EPS, blow and foundry parts: use the 3D tool design page (production tool design) of the part."} | 0.0 |
| 6 Generate the production tool design | ok | {'id': 14, 'part_id': 12, 'version': 1, 'rev_label': 'A', 'status': 'draft', 'kind': 'mould', 'part_type': 'blow', 'country': 'IN', 'as_of': '2026-10', 'summary': {'mould_base': '6030', 'cavities': 1, | 27.2 |
| 7 Tool design: no overlaps, valid solids | ok | 4 made parts, 34 standard 3D parts | 0.0 |
| 8 BOM: made parts with stock, weight, machining; bought-out list | ok | 4 part numbers, 6 bought-out lines, 353.0 kg steel | 0.0 |
| 9 Tool part drawings (PDF, DXF) and STEP of every made part | ok | 4 part numbers: PDF + DXF + STEP each | 31.8 |
| 10 Downloaded STEP opens again as a valid solid | ok | BLOW_HIGH-M-01 re-imports, 10813 cm³ | 0.1 |
| 11 3D viewer data (measure / view) | ok | 39 components for the 3D viewer | 0.6 |
| 12 Correct a component by STEP upload (round trip) | ok | revision B after upload, recalculated | 2.0 |
| 13 Toolmaker review signed | ok | 14 review items signed | 0.1 |
| 14 Release the design (drawing revision A) | ok | released | 1.6 |
| 15 Purchase orders: raw material, machining, bought-out (Excel + PDF) | ok | workbook 11 sheets, PO-1 4 lines, 3 PO PDFs + assembly sheet | 1.1 |
| 16 Supplier package ZIP (STEP, drawings, DXF, POs, assembly) | ok | 19 files, 1041 KB | 33.6 |
