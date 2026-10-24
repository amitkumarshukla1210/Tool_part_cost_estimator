# Design to Cost V2

New since V1:

- **Machine-aware tool design.** Before a design is made the software asks for the machine (tonnage, platen / bolster, tie bars, mould or shut height range, strokes, locating ring, flask).
  The base, the height (riser plate), the locating ring and the press follow the machine; every check is shown (Machine tab, review, Excel sheet). Skipped: the software recommends the machine the
  finished tool needs and names the closest machine of your list.
- **Process parameters for the best part quality** from the simulation and the material window (Process tab, Excel / PDF / PowerPoint, design pack): moulding, die casting, sheet metal, foundry, EPS, blow;
  quality warnings with the remedy. The simulation uses the material's melt, mould and ejection temperature.
- **Design skills.** The software learns from your corrected STEP files (plate thickness, cooling) and uses it in the next design; Skills page (switch off, edit, share, delete).
- New master data: Process windows, Process parameters, Skill knobs, machine rules `rec_…` in Tool detail rules.

Upgrade from V1: put `DesignToCost-V2.zip` in the folder `upgrades`, close the tool, double-click `Upgrade_Tool.bat`. Your data is kept; the new master-data rows are added.
