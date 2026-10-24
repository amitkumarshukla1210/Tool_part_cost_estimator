# Design to Cost V3

New since V2:

- **Drawings released for tooling carry all the technical data** to make the part: material grade, hardness, heat and surface treatment, surface roughness, general tolerances
  (ISO 2768 class f / m / c / v with the linear and angular tables), raw stock, weight, quantity, edge break and your own note points.
- **Review, add note points, download and upload.** A form per part on the tool-design page and an Excel *drawing data sheet* (one row per made part). Upload it and the PDF, DXF, bill of materials
  and purchase orders follow. Only drafts change; a released design is locked and its data is carried to the next revision.
- **One title block on every 2D drawing** (tool part, tool assembly, strip layout, blank; PDF and DXF): logo and "Design to Cost", release date, approved by, projection (third angle),
  drawing number, revision and the revision history (every data change is logged). New **A3 strip layout drawing** (PDF).
- New master data: *General tolerances* (EXAMPLE values: check against your copy of ISO 2768-1).

Upgrade from V2: put `DesignToCost-V3.zip` in the folder `upgrades`, close the tool, double-click `Upgrade_Tool.bat`. Your data is kept; the new table and rows are added.

All seeded country rates, machine prices and machine data are **EXAMPLE values**.
