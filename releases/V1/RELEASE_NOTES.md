# Design to Cost V1

New since V0:

- **Several users at the same time** (server mode, `Start_Server.bat`): roles User, Head of department, Admin.
- **Data by tool group**: each user sees and works only on the data of the groups the admin gave him / her; heads see and edit everything; the admin moves
  responsibilities (tick other groups) and the data follows. A mixed project shows each user his / her own parts.
- **Users page** (admin): create users, role, groups, reset password, deactivate, delete; table "Who sees which data".
- **My account**: every user changes his / her own password.
- Master data, rates and settings are changed by the head of department or the admin; users read them.
- Windows install check for Python 3.11, 3.12 and 3.13 (`scripts/check_windows_wheels.py`).

Upgrade from V0: put `DesignToCost-V1.zip` in the folder `upgrades`, close the tool, double-click `Upgrade_Tool.bat`. Your data is kept; older users are converted
(engineer = user, approver = head, viewer = user). To use several users start with `Start_Server.bat` instead of `Start_Tool.bat`.
