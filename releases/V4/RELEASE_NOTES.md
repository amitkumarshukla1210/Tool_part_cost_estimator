# Design to Cost V4

New since V3:

- **Every dimension of the tool part drawing has its tolerance**, in **mm or µm** (chosen per part): overall length, width, height (`160.00 ±0.5`),
  every hole (`H7 +0.015/0`, or `H7 +15/0 µm`; tapped holes `M14-6H`) with its position tolerance, every pocket and wire-cut opening (size and position). PDF and DXF.
- **Change any tolerance**: in the form on the tool-design page (*Dimension tolerances*) or in the Excel drawing data sheet (new sheet *Dimension tolerances*):
  `general` (ISO 2768 by size), `class`, a fit (`H7`, `g6`, `k6` …), `±0.02`, `+0.02/-0.01` or a thread class (`6H`). Each change is in the revision history.
- New master data: *Fit tolerances* (ISO 286 limits H6, H7, H8, h6, h7, g6, f7, k6, m6 by size) and *Feature tolerances* (the default per kind of feature).
  Both are EXAMPLE values: check them against your copy of the standards.

V3 (also in this version): technical data (grade, hardness, treatments, ISO 2768, roughness, notes) on every drawing; review form and Excel download / upload;
title block with logo, "Design to Cost", release date, approved by, projection and revision history on part, assembly and strip-layout drawings.

Upgrade: put `DesignToCost-V4.zip` in the folder `upgrades`, close the tool, double-click `Upgrade_Tool.bat`. Your data is kept; the new tables and rows are added.
