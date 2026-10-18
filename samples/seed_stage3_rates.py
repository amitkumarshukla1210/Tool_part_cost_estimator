"""Seeds the Stage 3 EXAMPLE rates into master_data/costing_db.sqlite (idempotent; run from the repo root).

India values come from the tool_materials / process_rates tables and the Stage 2 material rates; other countries are
India x a country cost factor, converted at the seeded forex rate. All rows are EXAMPLE values for you to replace."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app import costing_db, rates  # noqa: E402

# country cost factor vs India (EXAMPLE assumption, editable later in the rate library)
FACTOR = {"IN": 1.0, "CN": 0.95, "VN": 1.0, "TH": 1.05, "TW": 1.1, "KR": 1.15, "JP": 1.25, "US": 1.3, "DE": 1.4}
# new tool steels not yet in tool_materials (INR/kg, India EXAMPLE)
EXTRA_STEELS = {"SKD11": 520.0}
# India EXAMPLE unit rates for processes charged per quantity instead of per hour
UNIT_RATES = [("heat_treatment_per_kg", 90.0, "kg"), ("wire_cut_per_mm", 0.35, "mm"), ("wire_cut_per_cm2", 25.0, "cm2"),
              ("polishing_per_cm2", 6.0, "cm2"), ("painting_per_m2", 450.0, "m2"), ("transport_per_kg", 8.0, "kg")]
PLACEHOLDER = "EXAMPLE placeholder - replace with your market rate"


def main():
    con = sqlite3.connect(costing_db.path())
    forex = {r[0]: r[1] for r in con.execute("SELECT item, value FROM rates WHERE category='forex'")}
    ccy = {r[0]: r[1] for r in con.execute("SELECT code, currency FROM countries")}
    steels = {r[0]: r[1] for r in con.execute("SELECT code, rate_per_kg FROM tool_materials")} | EXTRA_STEELS
    hourly = {r[0]: r[1] for r in con.execute("SELECT code, rate_per_hour FROM process_rates")}
    mats = {r[0]: r[1] for r in con.execute("SELECT item, value FROM rates WHERE category='material' AND country='IN'")}
    scrap = {r[0]: r[1] for r in con.execute("SELECT item, value FROM rates WHERE category='material_scrap' AND country='IN'")}
    have = {r[:3] for r in con.execute("SELECT category, item, country FROM rates")}
    month = "2026-10"
    todo = []
    for c, f in FACTOR.items():
        cur = ccy[c]
        fx = 1.0 if cur == "INR" else forex[cur]
        def add(cat, item, inr, per):
            todo.append({"category": cat, "item": item, "country": c, "value": round(inr * f / fx, 4 if inr < 10 else 2),
                         "unit": f"{cur}/{per}", "currency": cur, "month": month, "source": PLACEHOLDER, "is_example": True,
                         "comment": "Stage 3 seed: India x country factor, at seeded forex"})
        for k, v in steels.items():
            add("tool_material", k, v, "kg")
        for k, v in hourly.items():
            add("tool_process", k, v, "h")
        for k, v, per in UNIT_RATES:
            add("tool_process", k, v, per)
        if c != "IN":
            for k, v in mats.items():
                add("material", k, v, "kg")
            for k, v in scrap.items():
                add("material_scrap", k, v, "kg")
    old = rates.settings()["approver_name"]
    rates.save_settings({"approver_name": "Example seed"})
    n = 0
    for r in todo:
        if (r["category"], r["item"], r["country"]) not in have:
            rates.create(r, approve=True, origin="seed")
            n += 1
    rates.save_settings({"approver_name": old})
    print(f"seeded {n} rates")


if __name__ == "__main__":
    main()
