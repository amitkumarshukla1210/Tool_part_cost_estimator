"""Heat-exchanger fin dies and fin part cost (roadmap stage 57).

A generic progressive fin die (any tube Ø, row pitch, hole pitch, rows across the strip and progressions per stroke) for
the four fin patterns plain / louver / slit / wavy, running on a fin press line (decoiler, oiler, fin press, stacker).

    Fin spec (typed per fin die)     pattern, tube / hole Ø, row pitch, hole pitch, rows, progressions, foil grade,
                                     thickness, width, FPI, fin rows, holes per fin, fin pack length, packs per year
    Mould & die → Fin patterns       stations each pattern adds (draw steps, ironing, louver, slit, wave), cut-off type, speed
    Mould & die → Fin presses        press data the line needs (foil width, SPM range, die height, coil Ø) per machine
    Countries … → Machines           the fin presses as machines (MHR by the MHR formulas, like every machine)

    die cost   = the tool cost engine (stage 4), part type 'fin': die set (Mould bases), BOM elements of part type fin
                 (sub-dies per station, punches, blades, wedges, springs ... steel × approved rate, bought-outs, processes
                 × MHR + labour), design, try-out on the fin press, overhead, profit, packing, transport, warranty
    press      = smallest fin press (Parameters fin → trial_machine_process) whose tonnage ≥ the die force (Cost formulas
                 fin_force), whose foil width ≥ the strip and whose bed takes the die set; or the press you choose
    part cost  = the Cost formulas of scope fin_part: foil RM − scrap + fin oil + press time × (MHR + operators × labour)
                 + stacking + regrinding + rejection + overhead + profit + packing + die amortisation + logistics, per fin
                 pack; also per fin and per kg

No number or rule is written here: every value is a master-data row (EXAMPLE until you replace it) or a formula in master
data, and every result is traced. seed() only ADDS rows (idempotent); existing rows are never changed.
"""

from __future__ import annotations

from . import costing_setup, formula, master_data, mould_db, rate_engine, rates
from .rm_cost import _parameter_row
from .tool_cost import ToolCostError, ToolInput, _ref, _Run, examples
from .trace import Trace

PART_TYPE = "fin"
PART_SCOPE, FORCE_SCOPE = "fin_part", "fin_force"
PATTERNS = ("plain", "louver", "slit", "wavy")
EXAMPLE = "EXAMPLE - typical fin die practice: replace with your die maker's / toolroom's value"
NOTE_BOM = "EXAMPLE fin die BOM rule (stage 57) - replace with your die maker's practice"


class FinDieError(ValueError):
    pass


# ---------------------------------------------------------------- master data (rows added by seed) ----------

# Fin patterns: pattern, name, draw steps, ironing, louver, slit, wave stations, rippled cut-off (1 = yes), speed factor
PATTERN_ROWS = [
    ("plain", "Plain / flat fin", 3, 0, 0, 0, 0, 0, 1.0),
    ("louver", "Louver fin (ironing + louver station)", 3, 1, 1, 0, 0, 0, 0.9),
    ("slit", "Slit / lanced fin (slit station)", 3, 0, 0, 1, 0, 0, 0.9),
    ("wavy", "Wavy / corrugated fin (wave station, rippled cut-off)", 3, 0, 0, 0, 1, 1, 0.85),
]

# Fin presses. Technical data per model: the Machines row (tonnage, motor, table = bed, floor area = machine L × W) for the MHR,
# and the Fin presses row (press line data). YKC series H-type: manufacturer's specification table (SOURCE_YADON);
# YKC-48SH-125: your machine specification sheet (the default press). Life, residual, maintenance, load factor and the
# machine price are EXAMPLE until you enter yours.
SOURCE_YADON = "https://www.yadonpress.com/shop/ykc-series-h-type-fin-press-line"
SOURCE_YOURS = "Your YKC-48SH-125 machine specification (Excel)"
DEFAULT_PRESS = "YKC-48SH-125"
_STD3 = "stroke 40 mm 150-300 SPM; 60 mm 150-230 SPM; 50 mm 150-260 SPM"
_BIG3 = "stroke 80 mm 150-200 SPM; 70 mm 150-220 SPM; 60 mm 150-230 SPM"
# model: kN, stroke mm, SPM min, SPM max, die height min / max, slide lift, slide L × W, table L × W, foil width, feed (sucking)
# length, coil ID min / max, coil OD, motor kW, machine L × W × H, variants, source
PRESSES = [
    ("YKC-48SH-125", 1250, 40, 150, 300, 280, 330, 130, 1500, 1350, 2000, 1360, 1080, 900, 150, 150, 1200, 22, 10000, 4500, 3800, "", SOURCE_YOURS),
    ("YKC-18-45", 450, 40, 150, 300, 260, 310, 80, 720, 780, 1300, 770, 400, 1000, 150, 150, 1000, 7.5, 7500, 3500, 3200, _STD3, SOURCE_YADON),
    ("YKC-24-63", 630, 40, 150, 300, 260, 310, 80, 800, 920, 1350, 900, 550, 1000, 150, 150, 1000, 7.5, 7500, 3500, 3500, _STD3, SOURCE_YADON),
    ("YKC-24A-63", 630, 40, 150, 300, 260, 310, 80, 1100, 920, 1600, 900, 550, 1000, 150, 150, 1000, 11, 10000, 4000, 3200, "", SOURCE_YADON),
    ("YKC-36-80", 800, 40, 150, 300, 280, 330, 100, 1055, 1220, 1600, 1200, 820, 900, 150, 150, 1200, 15, 10000, 4000, 3500, "", SOURCE_YADON),
    ("YKC-36A-100", 1000, 40, 150, 300, 280, 330, 120, 1300, 1190, 1800, 1200, 820, 900, 150, 150, 1200, 18.5, 10000, 4000, 3500, "", SOURCE_YADON),
    ("YKC-48A-125", 1250, 40, 150, 300, 280, 330, 130, 1500, 1350, 2000, 1360, 1080, 900, 150, 150, 1200, 22, 10000, 4500, 3800, "", SOURCE_YADON),
    ("YKC-48H-125", 1250, 30, 150, 400, 280, 330, 130, 1500, 1350, 2000, 1360, 1080, 900, 150, 150, 1200, 22, 10000, 4500, 3800, "", SOURCE_YADON),
    ("YKC-60A-160", 1600, 40, 150, 300, 280, 330, 150, 1450, 1540, 2000, 1500, 1200, 900, 150, 150, 1200, 22, 10000, 4800, 3800, "", SOURCE_YADON),
    ("YKC-160", 1600, 80, 150, 230, 280, 330, 130, 1300, 1190, 2000, 1200, 500, 900, 480, 550, 1200, 22, 10000, 4000, 3500, _BIG3, SOURCE_YADON),
    ("YKC-200", 2000, 80, 150, 230, 280, 330, 130, 1300, 1190, 2000, 1200, 500, 900, 480, 550, 1200, 22, 10000, 4000, 3500, _BIG3, SOURCE_YADON),
]
PRESS_COLS = ("machine_id", "capacity_kn", "stroke_mm", "spm_min", "spm_max", "die_height_min_mm", "die_height_max_mm", "slide_lift_mm",
              "slide_l_mm", "slide_w_mm", "table_l_mm", "table_w_mm", "max_foil_width_mm", "feed_length_mm", "coil_id_min_mm",
              "coil_id_max_mm", "coil_od_max_mm", "motor_kw", "machine_l_mm", "machine_w_mm", "machine_h_mm", "variants", "source")
PRESS_PROCESS = "Fin press"
PRESS_PRICE_REF = "PRESS-200"          # machine price / consumables copied (EXAMPLE) from this machine until you enter yours


def press_rows_seed() -> list[dict]:
    return [dict(zip(PRESS_COLS, p)) for p in PRESSES]


# Parameters rows of part type fin: parameter, value, unit, description (EXAMPLE unless the note says it is your spec)
PARAMETERS = [
    ("trial_machine_process", "Fin press", "", "Machines process of the fin presses (try-out and production press)"),
    ("press_machine_process", "Fin press", "", "Machines process of the fin presses"),
    ("trials", 2, "trials", "Fin die try-outs"),
    ("trial_hours_each", 8, "h", "Hours per fin die try-out"),
    ("trial_shots_each", 18000, "strokes", "Strokes per try-out (2 × 18,000 strokes ≈ 500 kg of 0.095 mm foil, as your spec's trial foil)"),
    ("press_safety_factor", 1.25, "x", "Fin press: tonnage over the die force"),
    ("tool_life_shots", 200000000, "strokes", "Fin die life: 200 million strokes (your spec INFB02M, guarantee)"),
    ("fin_die_life_strokes", 200000000, "strokes", "Fin die life for the part-cost amortisation (your spec: 200 million strokes)"),
    ("fin_regrind_strokes", 40000000, "strokes", "Cutting parts (pierce, slit, edge trim) reground every this many strokes (your spec: 40 million)"),
    ("fin_regrind_pct", 3, "% of die", "Cost of one regrind of the cutting parts, % of the die cost"),
    ("fin_spm", 220, "strokes/min", "Fin press speed of a plain fin die (× the pattern speed factor, ≤ the press SPM max)"),
    ("fin_oee_pct", 75, "%", "Fin press line OEE (coil changes, die adjustment, stops)"),
    ("fin_operators", 0.5, "persons", "Operators per fin press line (one runs two lines)"),
    ("fin_stack_s_per_pack", 45, "s", "Stacking / collecting / handling time per fin pack"),
    ("fin_oil_l_per_ac_set", 0.25, "L/AC set", "Fin oil (YBL) used per AC set, indoor + outdoor coils: 1 litre per 4 AC sets (your experience)"),
    ("default_fin_press", DEFAULT_PRESS, "", "Fin press used when the fin die spec names none (your press)"),
    ("fin_pierce_factor", 0.6, "× hole Ø", "Pierce hole before burring = factor × collar hole Ø (slug scrap)"),
    ("fin_edge_trim_mm", 5, "mm", "Edge trim each side of the strip (foil width = rows × row pitch + 2 × this)"),
    ("fin_shear_mpa", 75, "MPa", "Shear strength of the fin foil (Al H24 / H26) for the die force"),
    ("fin_form_force_factor", 1.5, "×", "Draw, collar, ironing and forming force over the cutting force"),
]

# Sizing rules (part type fin): die build-up used by the BOM rules
SIZING = [
    ("fin_fixed_stations", 7, "stations", "Stations every fin die has: pierce & burr, reflare, edge trim, pilot, row slit, feed, cut-off"),
    ("station_min_mm", 80, "mm", "Shortest station along the feed (a station is max(feed, this) long)"),
    ("die_end_mm", 150, "mm", "Die length added at each end (entry guide, cut-off and stacker side)"),
    ("die_side_mm", 60, "mm", "Die width added each side of the foil (guides, pillars, screws)"),
    ("subdie_h_mm", 45, "mm", "Sub-die / die button plate height"),
    ("holder_h_mm", 35, "mm", "Punch / draw holder plate height"),
    ("stripper_h_mm", 25, "mm", "Stripper plate height"),
    ("punch_len_mm", 55, "mm", "Punch length (pierce, draw, ironing, reflare)"),
    ("fin_spare_pct", 10, "%", "Spare punches / blades supplied with the die, % of the working set (free accessories)"),
    ("base_make_factor", 2.2, "× steel", "Fin die set priced by weight when it has no catalogue price: plate steel × this factor"),
]

# Process time parameters (part type fin)
TIMES = [
    ("cnc_setup_h", 4, "h", "CNC set-up per fin die"), ("cnc_plate_cm2_per_h", 300, "cm²/h", "CNC: plate area machined per hour"),
    ("wirecut_setup_h", 2, "h", "Wire cut set-up"), ("wirecut_mm2_per_h", 3000, "mm²/h", "Wire cut speed in hardened HSS / powder steel"),
    ("grind_setup_h", 2, "h", "Grinding set-up"), ("grind_cm2_per_h", 250, "cm²/h", "Surface grinding area per hour"),
    ("jig_grind_h_per_hole", 0.1, "h", "Jig grinding per punch / button hole"),
    ("punch_grind_h_each", 0.15, "h", "Profile grinding per punch"),
    ("louver_wirecut_h_each", 0.5, "h", "Wire cut per louver / slit punch & die set"),
    ("rippled_length_factor", 1.5, "×", "Rippled (wavy) cut-off profile length over the foil width"),
    ("assy_h_base", 160, "h", "Fitting & assembly of one fin die"), ("assy_h_per_punch", 0.15, "h", "Fitting per punch"),
    ("design_h_base", 120, "h", "Fin die design"), ("design_h_per_station", 12, "h", "Design per station"),
]

# Fin die sets (Mould bases, part type fin): size code, L, W, plate height each (top + bottom), all made to order
DIE_SETS = [("1209", 1200, 900, 80), ("1511", 1500, 1100, 90), ("1812", 1800, 1200, 100),
            ("2113", 2100, 1300, 100), ("2515", 2500, 1500, 110), ("3016", 3000, 1600, 120)]

# Tool steels of the fin die spec (Tool materials): new code, reference grade (density / rates copied, EXAMPLE), density, hardness
TOOL_STEELS = [
    ("HAP40 (Hitachi powder HSS)", "ASP 23 (powder HSS)", 8.1, "64 ±1 HRC", "Pierce & burring punches, edge trim, row slit blades"),
    ("SKH51 (JIS, = M2 HSS)", "M2 (1.3343) HSS", 8.1, "62 HRC", "Cut-off punch & die, draw / reflare punches, louver sets"),
    ("PX-5 (Daido pre-hardened)", "P20 (1.2311)", 7.85, "30-33 HRC prehardened", "Draw die plates, pierce holders, stripper plates"),
    ("SK3 (JIS carbon tool steel)", "O1 (1.2510)", 7.85, "58-62 HRC", "Drawing holders"),
]
HAP, SKH, PX5, SK3 = (t[0] for t in TOOL_STEELS)
P20 = "P20 (1.2311)"

# BOM elements (part type fin): element, category, quantity rule, unit cost rule (INR), material, weight rule, process,
# hours rule, amount rule, make. Variables: see FIN_VARS; sizing rules and time parameters of part type fin by name.
ST = "max(feed, station_min_mm)"
PUNCHES = "holes_per_stroke * (draw_steps + 3 + iron_st)"
BOM = [
    ("Draw sub-die plate", "made", "draw_steps", "0", PX5, f"die_w * {ST} * subdie_h_mm * density / 1e6", "", "0", "0", ""),
    ("Draw punch", "made", "draw_steps * holes_per_stroke", "0", SKH, "(hole_d + 3) ** 2 * punch_len_mm * density / 1e6", "", "0", "0", ""),
    ("Drawing holder", "made", "draw_steps", "0", SK3, f"die_w * {ST} * holder_h_mm * density / 1e6", "", "0", "0", ""),
    ("Pierce & burring punch", "made", "holes_per_stroke", "0", HAP, "(hole_d + 2) ** 2 * punch_len_mm * density / 1e6", "", "0", "0", ""),
    ("Pierce die button", "made", "holes_per_stroke", "0", HAP, "(hole_d + 8) ** 2 * subdie_h_mm * density / 1e6", "", "0", "0", ""),
    ("Pierce holder", "made", "1", "0", PX5, f"die_w * {ST} * holder_h_mm * density / 1e6", "", "0", "0", ""),
    ("Ironing punch", "made", "iron_st * holes_per_stroke", "0", HAP, "(hole_d + 2) ** 2 * punch_len_mm * density / 1e6", "", "0", "0", ""),
    ("Louver punch & die set", "made", "louver_st * die_rows * progressions", "0", SKH, "row_pitch * hole_pitch * subdie_h_mm * density / 1e6", "", "0", "0", ""),
    ("Slit (lance) punch & die set", "made", "slit_st * die_rows * progressions", "0", SKH, "row_pitch * hole_pitch * subdie_h_mm * density / 1e6", "", "0", "0", ""),
    ("Wave forming die (upper + lower)", "made", "2 * wave_st", "0", PX5, "die_w * feed * subdie_h_mm * density / 1e6", "", "0", "0", ""),
    ("Reflare punch", "made", "holes_per_stroke", "0", SKH, "(hole_d + 3) ** 2 * punch_len_mm * density / 1e6", "", "0", "0", ""),
    ("Edge trim punch & die", "made", "4", "0", HAP, f"{ST} * 30 * subdie_h_mm * density / 1e6", "", "0", "0", ""),
    ("Row slit blade (upper + lower)", "made", "2 * (die_rows - 1)", "0", HAP, f"{ST} * 3 * 40 * density / 1e6", "", "0", "0", ""),
    ("Cut-off punch & die", "made", "2", "0", SKH, "foil_w * 40 * 30 * density / 1e6", "", "0", "0", ""),
    ("Stripper plate", "made", "stations", "0", PX5, f"die_w * {ST} * stripper_h_mm * density / 1e6", "", "0", "0", ""),
    ("Pilots", "bought_out", "2 * die_rows", "250", "", "0", "", "0", "0", "Misumi / Punch"),
    ("Hitch-finger feed unit", "bought_out", "1", "350000", "", "0", "", "0", "0", "Die maker"),
    ("Digital wedge adjuster (draw / reflare)", "bought_out", "draw_steps + 1", "45000", "", "0", "", "0", "0", "Die maker"),
    ("Auto oiling & air-blow system", "bought_out", "1", "85000", "", "0", "", "0", "0", "Die maker"),
    ("Springs, guide posts, bushes, screws (set)", "bought_out", "1", "150000 + die_l * die_w / 50", "", "0", "", "0", "0", "Japan make (spec)"),
    ("Spare pierce & burring punches", "made", "ceil(holes_per_stroke * fin_spare_pct / 100)", "0", HAP, "(hole_d + 2) ** 2 * punch_len_mm * density / 1e6", "", "0", "0", ""),
    ("Spare row slit blades", "made", "ceil(2 * (die_rows - 1) * fin_spare_pct / 100)", "0", HAP, f"{ST} * 3 * 40 * density / 1e6", "", "0", "0", ""),
    ("Spare louver punch & die sets", "made", "ceil(louver_st * die_rows * progressions * fin_spare_pct / 100)", "0", SKH, "row_pitch * hole_pitch * subdie_h_mm * density / 1e6", "", "0", "0", ""),
    ("Wire cut - die buttons & holders", "process", "1", "0", "", "0", "Wire cut",
     "wirecut_setup_h + holes_per_stroke * (draw_steps + 2 + iron_st) * 3.1416 * (hole_d + 2) * subdie_h_mm / wirecut_mm2_per_h", "0", ""),
    ("Wire cut - louver / slit punches", "process", "1", "0", "", "0", "Wire cut",
     "(louver_st + slit_st) * die_rows * progressions * louver_wirecut_h_each", "0", ""),
    ("Wire cut - rippled cut-off blades", "process", "rippled", "0", "", "0", "Wire cut",
     "wirecut_setup_h + 2 * foil_w * rippled_length_factor * 40 / wirecut_mm2_per_h", "0", ""),
    ("Jig grinding - punch & button holes", "process", "1", "0", "", "0", "Grinding", f"{PUNCHES} * jig_grind_h_per_hole", "0", ""),
    ("Profile grinding - punches", "process", "1", "0", "", "0", "Grinding", f"{PUNCHES} * punch_grind_h_each", "0", ""),
    ("CNC machining - plates & holders", "process", "1", "0", "", "0", "CNC milling",
     f"cnc_setup_h + 4 * stations * die_w * {ST} / 100 / cnc_plate_cm2_per_h", "0", ""),
    ("Surface grinding", "process", "1", "0", "", "0", "Grinding", "grind_setup_h + 6 * die_l * die_w / 100 / grind_cm2_per_h", "0", ""),
    ("Vacuum heat treatment (HSS / powder steel)", "process", "1", "0", "", "0", "Vacuum heat treatment (per kg)", "0",
     f"{PUNCHES} * (hole_d + 3) ** 2 * punch_len_mm * 8.1 / 1e6 + 2 * foil_w * 40 * 30 * 8.1 / 1e6", ""),
    ("Heat treatment (plates & holders)", "process", "1", "0", "", "0", "Heat treatment (per kg)", "0",
     f"stations * die_w * {ST} * (stripper_h_mm + holder_h_mm) * 7.85 / 1e6", ""),
    ("Fitting & assembly", "process", "1", "0", "", "0", "Fitting & assembly", f"assy_h_base + assy_h_per_punch * {PUNCHES}", "0", ""),
    ("Die design", "process", "1", "0", "", "0", "Design", "design_h_base + design_h_per_station * stations", "0", ""),
]

# Fin foil materials (Materials, part type fin): alloy, tempers, density; plain and hydrophilic coated
FOIL_ALLOYS = [("1050", 2.71), ("1100", 2.71), ("1145", 2.70), ("1200", 2.71), ("3003", 2.73), ("3005", 2.73), ("3102", 2.72),
               ("7072", 2.72), ("8006", 2.73), ("8011", 2.71), ("8079", 2.71)]
FOIL_TEMPERS = ("O", "H22", "H24", "H26")
FOIL_COATS = ("plain", "hydrophilic coated", "epoxy coated (anti-corrosion)")
# copper fin foil (main material Copper fin foil): grade, density
COPPER_FOILS = [("Cu fin foil C1100-O (ETP)", 8.94), ("Cu fin foil C1100-H (ETP)", 8.94), ("Cu fin foil C1220-O (DHP)", 8.94)]
COPPER_TYPE, COPPER_RATE_REF = "Copper fin foil", "Copper"
FOIL_TYPE = "Aluminium fin foil"
FOIL_RATE_REF = "Aluminium 1100 / 1050 (commercially pure)"   # its approved RM and scrap rates copied (EXAMPLE) per country
FOIL_NOTE = ("EXAMPLE fin foil grade (stage 57): density typical; price = {ref} until you enter your supplier price "
             "(foil conversion premium and coating not yet in it)")
OIL_ITEM = "Fin oil YBL (per litre)"
OIL_REF_INR = 180            # INR per litre, EXAMPLE until you enter the YBL price (other countries by forex)


def foil_grades() -> list[tuple[str, float]]:
    return [(f"Al fin foil {a}-{t} {c}", d) for a, d in FOIL_ALLOYS for t in FOIL_TEMPERS for c in FOIL_COATS]


def all_foils() -> list[tuple[str, float, str, str]]:
    """(grade, density, main material, rate reference) of every fin foil."""
    return ([(n, d, FOIL_TYPE, FOIL_RATE_REF) for n, d in foil_grades()]
            + [(n, d, COPPER_TYPE, COPPER_RATE_REF) for n, d in COPPER_FOILS])


# Cost formulas: (scope, name, label, formula, unit, is_result, description)
FORMULAS = [
    (FORCE_SCOPE, "pierce_force_t", "Pierce force", "holes_per_stroke * 3.1416 * fin_pierce_factor * hole_d * foil_t * fin_shear_mpa / 9806.65", "t", False,
     "Every hole pierced in one stroke: Σ perimeter × thickness × shear strength"),
    (FORCE_SCOPE, "cut_force_t", "Cut-off, edge trim and row slit force", "(foil_w + 2 * feed + (die_rows - 1) * feed) * foil_t * fin_shear_mpa / 9806.65", "t", False,
     "Cut-off across the strip, edge trim both sides and every row slit over one feed"),
    (FORCE_SCOPE, "die_force_t", "Fin die force", "(pierce_force_t + cut_force_t) * (1 + fin_form_force_factor)", "t", False,
     "Cutting force plus draw, collar, ironing and forming (factor of the cutting force)"),
    (FORCE_SCOPE, "press_force_t", "Fin press force needed", "die_force_t * press_safety_factor", "t", True, "Die force × press safety factor"),
    (PART_SCOPE, "feed_mm", "Feed per stroke", "progressions * hole_pitch", "mm", False, "Progressions × hole pitch"),
    (PART_SCOPE, "fins_across", "Fins across the strip", "floor(die_rows / fin_rows)", "fins", False, "Rows of the die ÷ fin rows (the rest is slit off as scrap)"),
    (PART_SCOPE, "fin_w_mm", "Fin width", "fin_rows * row_pitch", "mm", False, ""),
    (PART_SCOPE, "fin_l_mm", "Fin length", "fin_holes * hole_pitch", "mm", False, ""),
    (PART_SCOPE, "fins_per_stroke", "Fins per stroke", "fins_across * progressions / fin_holes", "fins", False, ""),
    (PART_SCOPE, "fins_per_pack", "Fins per pack", "ceil(pack_length * fpi / 25.4)", "fins", False, "Pack length (inch) × fins per inch"),
    (PART_SCOPE, "strokes_per_pack", "Press strokes per pack", "fins_per_pack / fins_per_stroke", "strokes", False, ""),
    (PART_SCOPE, "gross_kg", "Foil used per pack", "strokes_per_pack * foil_w * feed_mm * foil_t * density / 1e6", "kg", False,
     "Strokes × foil width × feed × thickness × density"),
    (PART_SCOPE, "pierce_d_mm", "Pierce hole Ø", "fin_pierce_factor * hole_d", "mm", False, ""),
    (PART_SCOPE, "net_kg", "Net fin weight per pack", "fins_per_pack * (fin_w_mm * fin_l_mm - fin_rows * fin_holes * 0.7854 * pierce_d_mm ** 2) * foil_t * density / 1e6", "kg", False,
     "Fin area less the pierced slugs (the collar is drawn from the foil)"),
    (PART_SCOPE, "scrap_kg", "Scrap per pack", "gross_kg - net_kg", "kg", False, "Slugs, edge trim and rows slit off"),
    (PART_SCOPE, "rm_cost", "Foil RM cost (net of scrap)", "gross_kg * rm_rate - scrap_kg * scrap_rate", "{cur}", False, ""),
    (PART_SCOPE, "oil_l", "Fin oil (YBL) per pack", "gross_kg * fin_oil_l_per_ac_set / foil_kg_per_ac_set", "L", False,
     "Oil of one AC set (1 L per 4 AC sets) shared by foil kg: this pack's foil ÷ the foil of one AC set (indoor + outdoor)"),
    (PART_SCOPE, "oil_cost", "Fin oil (YBL)", "oil_l * oil_rate", "{cur}", False, ""),
    (PART_SCOPE, "spm", "Press speed", "spm_typed if spm_typed > 0 else min(fin_spm * spm_factor, press_spm_max)", "strokes/min", False,
     "The SPM you typed; else the plain-fin speed × pattern factor, not above the press SPM max"),
    (PART_SCOPE, "press_h", "Press hours per pack", "strokes_per_pack / (spm * 60 * fin_oee_pct / 100)", "h", False, ""),
    (PART_SCOPE, "process_cost", "Fin press line", "press_h * (mhr + fin_operators * labour_rate)", "{cur}", False, "Press hours × (MHR + operators × labour rate)"),
    (PART_SCOPE, "stacking_cost", "Stacking & handling", "fin_stack_s_per_pack / 3600 * labour_rate", "{cur}", False, ""),
    (PART_SCOPE, "regrind_cost", "Die regrinding", "die_cost * fin_regrind_pct / 100 * strokes_per_pack / fin_regrind_strokes", "{cur}", False,
     "One regrind of the cutting parts every fin_regrind_strokes"),
    (PART_SCOPE, "reject_cost", "Rejection", "(rm_cost + oil_cost + process_cost + stacking_cost) * rejection_pct / (100 - rejection_pct)", "{cur}", False, ""),
    (PART_SCOPE, "overhead", "Overhead on conversion", "(process_cost + stacking_cost) * part_overhead_pct / 100", "{cur}", False, ""),
    (PART_SCOPE, "before_profit", "Cost before profit", "rm_cost + oil_cost + process_cost + stacking_cost + regrind_cost + reject_cost + overhead", "{cur}", False, ""),
    (PART_SCOPE, "profit", "Profit", "before_profit * profit_pct / 100", "{cur}", False, ""),
    (PART_SCOPE, "packing", "Packing", "(before_profit + profit) * packing_pct / 100", "{cur}", False, ""),
    (PART_SCOPE, "programme_strokes", "Strokes over the programme", "packs_per_year * programme_years * strokes_per_pack", "strokes", False, ""),
    (PART_SCOPE, "amortisation", "Die amortisation", "die_cost * strokes_per_pack / min(fin_die_life_strokes, programme_strokes)", "{cur}", False,
     "Die cost spread over its life, or over the programme when shorter"),
    (PART_SCOPE, "logistics", "Logistics", "net_kg * transport_rate", "{cur}", False, ""),
    (PART_SCOPE, "pack_cost", "Fin pack cost", "before_profit + profit + packing + amortisation + logistics", "{cur}", True, "Cost of one fin pack"),
    (PART_SCOPE, "cost_per_fin", "Cost per fin", "pack_cost / fins_per_pack", "{cur}", False, ""),
    (PART_SCOPE, "cost_per_kg", "Cost per kg of fin", "pack_cost / net_kg", "{cur}", False, ""),
]

# Values worked out by this engine that the fin formulas use (Formula inputs, source piece)
FIN_ITEMS = {
    "die_rows": ("Rows across the strip (die)", "rows"), "progressions": ("Progressions per stroke", "holes"),
    "holes_per_stroke": ("Holes per stroke = rows × progressions", "holes"), "row_pitch": ("Row pitch", "mm"),
    "hole_pitch": ("Hole pitch in a row", "mm"), "hole_d": ("Fin hole (collar) Ø", "mm"), "foil_t": ("Foil thickness", "mm"),
    "foil_w": ("Foil width", "mm"), "feed": ("Feed per stroke", "mm"), "density": ("Foil density", "g/cm³"),
    "fin_rows": ("Fin rows (coil depth)", "rows"), "fin_holes": ("Holes along one fin", "holes"), "fpi": ("Fins per inch", "FPI"),
    "pack_length": ("Fin pack length", "mm"), "spm_factor": ("Pattern speed factor", "×"),
    "press_spm_max": ("Press SPM max", "strokes/min"), "spm_typed": ("SPM typed in the fin die spec (0 = not typed)", "strokes/min"),
    "foil_kg_per_ac_set": ("Foil of one AC set, indoor + outdoor coils", "kg"), "rm_rate": ("Foil rate", "{cur}/kg"), "scrap_rate": ("Scrap value", "{cur}/kg"),
    "mhr": ("Machine hour rate of the fin press", "{cur}/h"), "labour_rate": ("Operator labour rate", "{cur}/h"),
    "die_cost": ("Cost of one fin die", "{cur}"), "packs_per_year": ("Fin packs per year", "packs/yr"),
    "programme_years": ("Programme years", "years"),
}
FORCE_INPUTS = ("holes_per_stroke", "hole_d", "foil_t", "foil_w", "feed", "die_rows")
PART_PARAMS = ("fin_spm", "fin_oee_pct", "fin_operators", "fin_stack_s_per_pack", "fin_oil_l_per_ac_set", "fin_die_life_strokes",
               "fin_regrind_strokes", "fin_regrind_pct", "fin_pierce_factor", "rejection_pct", "part_overhead_pct", "packing_pct")
FORCE_PARAMS = ("fin_pierce_factor", "fin_shear_mpa", "fin_form_force_factor", "press_safety_factor")
PART_RATES = (("oil_rate", "Fin oil per litre", "process_unit", OIL_ITEM, "{cur}/L"),
              ("profit_pct", "Profit", "profit", "profit_pct", "%"),
              ("transport_rate", "Transport per kg", "process_unit", "Transport (per kg)", "{cur}/kg"))


def _example_rate(cat, item, country, value, unit, cur, month, source) -> None:
    rates.create({"category": cat, "item": item, "country": country, "value": value, "unit": unit, "currency": cur,
                  "month": month, "source": source, "is_example": True}, approve=True, origin="seed", approver="Example seed", system=True)


def _seed_rates() -> int:
    from .material_grades import _approved, _copy_rates, _has_rate
    n = 0
    for name, _d, _t, ref in all_foils():
        n += _copy_rates("material", ref, name) + _copy_rates("material_scrap", ref, name)
    for code, ref, *_ in TOOL_STEELS:
        n += _copy_rates("tool_material", ref, code)
    for p in PRESSES:
        n += _copy_rates("machine_price", PRESS_PRICE_REF, p[0]) + _copy_rates("consumables", PRESS_PRICE_REF, p[0])
    # fin oil: INR value in India, other countries the same value converted by that month's approved forex
    countries = {c["code"]: c["currency"] for c in costing_setup.tables()["countries"]}
    for t in _approved("process_unit", "Transport (per kg)"):
        country, cur, month = t["country"], countries.get(t["country"]), t["month"]
        if not cur or _has_rate("process_unit", OIL_ITEM, country):
            continue
        if cur == rates.BASE_CURRENCY:
            value = OIL_REF_INR
        else:
            try:
                value = round(OIL_REF_INR / rates.lookup("forex", cur, "", month)["value"], 4)
            except rates.RateError:
                continue
        _example_rate("process_unit", OIL_ITEM, country, value, f"{cur}/L", cur, month,
                      f"EXAMPLE placeholder (stage 57): YBL fin oil ₹{OIL_REF_INR}/L converted by forex - replace with the YBL price")
        n += 1
    return n


def seed() -> dict:
    """Add the fin die master data that is missing. Idempotent; existing rows and rates are never changed."""
    out = {"parameters": 0, "materials": 0, "machines": 0, "formulas": 0, "inputs": 0, "mould_db": 0, "rates": 0}
    md = master_data.tables()
    have = {(r["part_type"], r["parameter"]) for r in md["Parameters"]}
    for k, v, unit, desc in PARAMETERS:
        if (PART_TYPE, k) not in have:
            md["Parameters"].append({"part_type": PART_TYPE, "parameter": k, "value": v, "unit": unit,
                                     "description": f"{desc} (stage 57; EXAMPLE unless it says 'your spec')"})
            out["parameters"] += 1
    mats = {(r["part_type"], r["material"]) for r in md["Materials"]}
    first = True
    for name, density, main, ref in all_foils():
        if (PART_TYPE, name) not in mats:
            row = {k: "" for k in md["Materials"][0]} if md["Materials"] else {}
            row |= {"part_type": PART_TYPE, "material": name, "material_type": main,
                    "recommended": "yes" if name in (DEFAULT_MATERIAL, COPPER_FOILS[0][0]) else "",
                    "density_g_cm3": density, "notes": FOIL_NOTE.format(ref=ref)}
            md["Materials"].append(row)
            out["materials"] += 1
        first = False
    if out["parameters"] or out["materials"]:
        master_data.write(md)

    cs = costing_setup.tables()
    mids = {m["machine_id"] for m in cs["machines"]}
    for r in press_rows_seed():
        if r["machine_id"] not in mids:
            cs["machines"].append({"machine_id": r["machine_id"], "name": f"Fin press {r['machine_id']} ({r['capacity_kn'] / 10:g} t)",
                                   "process": PRESS_PROCESS, "power_kw": r["motor_kw"], "load_factor_pct": 60,
                                   "floor_area_m2": round(r["machine_l_mm"] * r["machine_w_mm"] / 1e6, 1), "life_years": 15,
                                   "residual_pct": 10, "maintenance_pct": 4, "tonnage_t": r["capacity_kn"] / 10,
                                   "length_mm": r["table_l_mm"], "width_mm": r["table_w_mm"], "is_example": True,
                                   "notes": f"Technical data: {r['source']}. Load factor, life, residual, maintenance and the machine "
                                            "price are EXAMPLE until you enter yours."})
            out["machines"] += 1
    fhave = {(r["scope"], r["name"]) for r in cs["cost_formulas"]}
    for scope, name, label, text, unit, res, desc in FORMULAS:
        if (scope, name) not in fhave:
            cs["cost_formulas"].append({"scope": scope, "name": name, "label": label, "formula": text, "unit": unit,
                                        "is_result": res, "description": (desc + " (stage 57, EXAMPLE)").strip()})
            out["formulas"] += 1
    ihave = {(r["scope"], r["variable"]) for r in cs["formula_inputs"]}

    def add_input(scope, var, label, source, cat, item, money, unit):
        if (scope, var) not in ihave:
            cs["formula_inputs"].append({"scope": scope, "variable": var, "label": label, "source": source, "category": cat,
                                         "item": item, "is_money": money, "unit": unit})
            ihave.add((scope, var))
            out["inputs"] += 1
    for var, (label, unit) in FIN_ITEMS.items():
        add_input(PART_SCOPE, var, label, "piece", "", var, "{cur}" in unit, unit)
    for var in PART_PARAMS:
        add_input(PART_SCOPE, var, var.replace("_", " "), "parameter", "", var, False, "")
    for var, label, cat, item, unit in PART_RATES:
        add_input(PART_SCOPE, var, label, "rate", cat, item, "{cur}" in unit, unit)
    for var in FORCE_INPUTS:
        add_input(FORCE_SCOPE, var, FIN_ITEMS[var][0], "piece", "", var, False, FIN_ITEMS[var][1])
    for var in FORCE_PARAMS:
        add_input(FORCE_SCOPE, var, var.replace("_", " "), "parameter", "", var, False, "")
    if out["machines"] or out["formulas"] or out["inputs"]:
        costing_setup.write(cs)

    db = mould_db.tables()
    n0 = sum(len(v) for v in db.values())
    have = {r["pattern"] for r in db["fin_patterns"]}
    for p, name, ds, ir, lv, sl, wv, rip, spf in PATTERN_ROWS:
        if p not in have:
            db["fin_patterns"].append({"pattern": p, "name": name, "draw_steps": ds, "iron_stations": ir, "louver_stations": lv,
                                       "slit_stations": sl, "wave_stations": wv, "rippled_cutoff": rip, "spm_factor": spf,
                                       "is_example": True, "notes": EXAMPLE})
    have = {r["machine_id"] for r in db["fin_presses"]}
    for r in press_rows_seed():
        if r["machine_id"] not in have:
            db["fin_presses"].append(r | {"is_example": False, "default_press": r["machine_id"] == DEFAULT_PRESS,
                                          "notes": ("Your machine, the default press" if r["machine_id"] == DEFAULT_PRESS else
                                                    "Manufacturer's specification table") + (f"; variants: {r['variants']}" if r["variants"] else "")})
    for table, rows in (("sizing_rules", SIZING), ("time_parameters", TIMES)):
        have = {(r["part_type"], r["parameter"]) for r in db[table]}
        for k, v, unit, desc in rows:
            if (PART_TYPE, k) not in have:
                db[table].append({"part_type": PART_TYPE, "parameter": k, "value": v, "unit": unit,
                                  "description": f"{desc} (stage 57)", "is_example": True})
    have = {(r["part_type"], r["size_code"]) for r in db["mould_bases"]}
    for code, L, W, ph in DIE_SETS:
        if (PART_TYPE, code) not in have:
            db["mould_bases"].append({"part_type": PART_TYPE, "series": "Fin die set (made to order)", "size_code": code,
                                      "length_mm": L, "width_mm": W, "max_insert_length_mm": L - 100, "max_insert_width_mm": W - 100,
                                      "a_plate_mm": 0, "b_plate_mm": 0, "clamp_plates_mm": ph, "support_plate_mm": 0,
                                      "spacer_block_mm": 0, "ejector_plates_mm": 0, "stack_height_mm": 2 * ph + 120,
                                      "weight_kg": round(L * W * 2 * ph * 7.85 / 1e6, 1), "cost": 0, "material": P20,
                                      "make": "Made to order", "is_example": True,
                                      "notes": "EXAMPLE fin die set (upper + lower plates P20, guide posts): priced by weight × base_make_factor"})
    tools = {r["code"]: r for r in db["tool_materials"]}
    for code, ref, density, hardness, application in TOOL_STEELS:
        if code not in tools and ref in tools:
            db["tool_materials"].append(dict(tools[ref]) | {"code": code, "density_g_cm3": density, "hardness": hardness, "make": "",
                                                            "is_example": True,
                                                            "notes": f"EXAMPLE grade (stage 57, fin die spec): {application}; price = {ref} until you enter yours"})
            tools[code] = db["tool_materials"][-1]
    have = {(r["part_type"], r["element"]) for r in db["bom_elements"]}
    for el, cat, qty, unit_cost, mat, wt, proc, hrs, amt, make in BOM:
        if (PART_TYPE, el) not in have:
            db["bom_elements"].append({"part_type": PART_TYPE, "element": el, "category": cat, "quantity_rule": qty,
                                       "unit_cost_rule": unit_cost, "material_code": mat, "weight_rule": wt, "process_code": proc,
                                       "hours_rule": hrs, "amount_rule": amt, "make": make, "std_part": "", "price_each_inr": 0,
                                       "operations": "", "is_example": True, "notes": NOTE_BOM})
    out["mould_db"] = sum(len(v) for v in db.values()) - n0
    if out["mould_db"]:
        mould_db.write(db)
    out["rates"] = _seed_rates()
    return out


def validate(clean: dict) -> None:
    """Mould & die database check of the fin tables."""
    for i, r in enumerate(clean.get("fin_patterns", []), start=2):
        if r["spm_factor"] <= 0 or r["draw_steps"] < 1:
            raise mould_db.MouldDbError(f"Fin patterns row {i}: speed factor must be more than 0 and draw steps at least 1.")
    for i, r in enumerate(clean.get("fin_presses", []), start=2):
        if r["spm_max"] < r["spm_min"] or r["die_height_max_mm"] < r["die_height_min_mm"] or r["max_foil_width_mm"] <= 0:
            raise mould_db.MouldDbError(f"Fin presses row {i}: SPM / die height max must not be below min, foil width more than 0.")
    if sum(1 for r in clean.get("fin_presses", []) if r.get("default_press")) > 1:
        raise mould_db.MouldDbError("Fin presses: mark only one press as the default press.")


# ---------------------------------------------------------------- the fin spec ----------

# key: (label, unit, default (your IFB φ5 × 66R × 4P louver die), minimum, maximum)
SPEC = {
    "tube_od_mm": ("Tube outside Ø", "mm", 5.0, 3, 20),
    "hole_d_mm": ("Fin hole (collar) Ø", "mm", 5.2, 3, 20),
    "row_pitch_mm": ("Row pitch (between rows across the strip)", "mm", 12.7, 5, 60),
    "hole_pitch_mm": ("Hole pitch (between holes in a row)", "mm", 16.0, 5, 60),
    "die_rows": ("Rows across the strip (die)", "rows", 66, 1, 200),
    "progressions": ("Progressions per stroke", "holes", 4, 1, 12),
    "foil_t_mm": ("Foil thickness", "mm", 0.095, 0.05, 0.3),
    "foil_width_mm": ("Foil width (0 = rows × row pitch + 2 × edge trim)", "mm", 848.0, 0, 2000),
    "fpi": ("Fins per inch", "FPI", 21.0, 6, 40),
    "fin_rows": ("Fin rows (coil depth)", "rows", 2, 1, 12),
    "fin_holes": ("Holes along one fin", "holes", 24, 1, 400),
    "pack_length_mm": ("Fin pack length", "mm", 700.0, 10, 5000),
    "packs_per_year": ("Fin packs per year", "packs/yr", 100000, 1, 1e8),
    "programme_years": ("Programme years", "years", 5, 0.5, 30),
    "tools_count": ("Fin dies over the programme", "dies", 1, 1, 50),
    "spm": ("Press speed SPM (0 = plain-fin speed × pattern factor)", "strokes/min", 0, 0, 1000),
    "foil_kg_per_ac_set": ("Foil of one AC set, indoor + outdoor coils (for the oil)", "kg", 5.0, 0.1, 500),
}
DEFAULT_MATERIAL = "Al fin foil 8011-H24 hydrophilic coated"


def default_spec() -> dict:
    return {k: v[2] for k, v in SPEC.items()} | {"pattern": "louver", "material": DEFAULT_MATERIAL, "country": "", "press": "",
                                                "staggered": True, "warranty": True}


def normalise(spec: dict | None) -> dict:
    s = default_spec() | {k: v for k, v in (spec or {}).items() if v not in (None, "")}
    for k, (label, unit, _d, lo, hi) in SPEC.items():
        try:
            s[k] = float(s[k])
        except (TypeError, ValueError):
            raise FinDieError(f"{label}: '{s[k]}' is not a number.") from None
        if not lo <= s[k] <= hi:
            raise FinDieError(f"{label} must be between {lo:g} and {hi:g} {unit}.")
    for k in ("die_rows", "progressions", "fin_rows", "fin_holes", "tools_count"):
        if not float(s[k]).is_integer():
            raise FinDieError(f"{SPEC[k][0]} must be a whole number.")
        s[k] = int(s[k])
    if s["pattern"] not in PATTERNS:
        raise FinDieError(f"Fin pattern must be one of {', '.join(PATTERNS)}.")
    if s["fin_rows"] > s["die_rows"]:
        raise FinDieError("Fin rows cannot be more than the rows across the strip.")
    if s["hole_d_mm"] < s["tube_od_mm"]:
        raise FinDieError("The fin hole (collar) Ø must be at least the tube Ø.")
    s["country"] = (s.get("country") or "").upper()
    s["press"] = (s.get("press") or "").strip()
    s["staggered"] = bool(s.get("staggered", True))
    s["warranty"] = bool(s.get("warranty", True))
    return s


def default_press() -> str:
    """The press marked default in Fin presses, else Parameters fin → default_fin_press."""
    row = next((r for r in mould_db.tables()["fin_presses"] if r.get("default_press")), None)
    if row:
        return row["machine_id"]
    return str((_parameter_row(PART_TYPE, "default_fin_press") or {}).get("value") or "")


def pattern_row(pattern: str) -> dict:
    row = next((r for r in mould_db.tables()["fin_patterns"] if r["pattern"] == pattern), None)
    if not row:
        raise FinDieError(f"Mould & die database → Fin patterns has no row '{pattern}'.")
    return row


def press_rows() -> dict:
    return {r["machine_id"]: r for r in mould_db.tables()["fin_presses"]}


def _param(name: str) -> dict:
    row = _parameter_row(PART_TYPE, name)
    if row is None or isinstance(row["value"], str) and name not in master_data.TEXT_PARAMETERS:
        raise FinDieError(f"Master data → Parameters has no '{name}' for part type fin (run the stage 57 seed).")
    return row


def _density(material: str) -> dict:
    row = next((r for r in master_data.tables()["Materials"] if r["part_type"] == PART_TYPE and r["material"] == material), None)
    if not row:
        raise FinDieError(f"Fin foil '{material}' is not in Master data → Materials (part type fin).")
    return row


def foil_width(s: dict) -> tuple[float, str]:
    """Typed foil width, else rows × row pitch + 2 × edge trim (Parameters)."""
    if s["foil_width_mm"]:
        return s["foil_width_mm"], "typed"
    trim = float(_param("fin_edge_trim_mm")["value"])
    return s["die_rows"] * s["row_pitch_mm"] + 2 * trim, f"rows × row pitch + 2 × {trim:g} mm edge trim"


# ---------------------------------------------------------------- die cost ----------

FIN_VARS = {
    "die_rows": ("Rows across the strip", "rows"), "progressions": ("Progressions per stroke", "holes"),
    "holes_per_stroke": ("Holes per stroke", "holes"), "row_pitch": ("Row pitch", "mm"), "hole_pitch": ("Hole pitch", "mm"),
    "hole_d": ("Fin hole (collar) Ø", "mm"), "t": ("Foil thickness", "mm"), "foil_t": ("Foil thickness", "mm"),
    "foil_w": ("Foil width", "mm"), "feed": ("Feed per stroke", "mm"),
    "draw_steps": ("Draw steps", "stations"), "iron_st": ("Ironing stations", "stations"), "louver_st": ("Louver stations", "stations"),
    "slit_st": ("Slit stations", "stations"), "wave_st": ("Wave stations", "stations"), "rippled": ("Rippled cut-off (1 = yes)", ""),
}


class _FinDieRun(_Run):
    def __init__(self, inp: ToolInput, s: dict, pattern: dict):
        super().__init__(inp, None)
        self.s, self.pattern = s, pattern
        self.foil_w, self.foil_w_note = foil_width(s)

    def var(self, name: str) -> str:
        nid = f"v:{name}"
        if nid in self.trace.nodes:
            return nid
        t, s, p = self.trace, self.s, self.pattern
        spec_src = {"type": "user", "note": "Fin die spec (Fin dies page)"}
        pat_src = lambda col: {"type": "master", "sheet": "Mould & die database → Fin patterns", "row": p["pattern"],
                               "is_example": bool(p["is_example"]),
                               "ref": _ref("mould_db", "fin_patterns", {"pattern": p["pattern"]}, col)}
        direct = {"die_rows": s["die_rows"], "progressions": s["progressions"], "row_pitch": s["row_pitch_mm"],
                  "hole_pitch": s["hole_pitch_mm"], "hole_d": s["hole_d_mm"], "t": s["foil_t_mm"], "foil_t": s["foil_t_mm"]}
        cols = {"draw_steps": "draw_steps", "iron_st": "iron_stations", "louver_st": "louver_stations", "slit_st": "slit_stations",
                "wave_st": "wave_stations", "rippled": "rippled_cutoff"}
        if name in direct:
            label, unit = FIN_VARS[name]
            t.add_input(nid, label, float(direct[name]), unit, spec_src)
        elif name in cols:
            label, unit = FIN_VARS[name]
            t.add_input(nid, f"{label} · {p['name']}", float(p[cols[name]]), unit, pat_src(cols[name]))
        elif name == "foil_w":
            if s["foil_width_mm"]:
                t.add_input(nid, "Foil width", self.foil_w, "mm", spec_src)
            else:
                row = _param("fin_edge_trim_mm")
                trim = self.master("v:fin_edge_trim_mm", "Edge trim each side", row["value"], "mm", "Parameters", "fin / fin_edge_trim_mm",
                                   ref=_ref("master_data", "Parameters", {"part_type": row["part_type"], "parameter": "fin_edge_trim_mm"}, "value"))
                t.compute(nid, "Foil width", "die_rows * row_pitch + 2 * trim", "mm",
                          names={"die_rows": self.var("die_rows"), "row_pitch": self.var("row_pitch"), "trim": trim})
        elif name == "holes_per_stroke":
            t.compute(nid, "Holes per stroke", "die_rows * progressions", "holes",
                      names={k: self.var(k) for k in ("die_rows", "progressions")})
        elif name == "feed":
            t.compute(nid, "Feed per stroke", "progressions * hole_pitch", "mm", names={k: self.var(k) for k in ("progressions", "hole_pitch")})
        elif name == "stations":
            t.compute(nid, "Stations of the fin die",
                      "draw_steps + iron_st + louver_st + slit_st + wave_st + fin_fixed_stations", "stations",
                      names={k: self.var(k) for k in ("draw_steps", "iron_st", "louver_st", "slit_st", "wave_st", "fin_fixed_stations")},
                      description="Draw steps and the pattern's stations (Fin patterns) + the stations every fin die has (Sizing rules)")
        elif name == "die_l":
            t.compute(nid, "Fin die length (along the feed)", "stations * max(feed, station_min_mm) + 2 * die_end_mm", "mm",
                      names={k: self.var(k) for k in ("stations", "feed", "station_min_mm", "die_end_mm")})
        elif name == "die_w":
            t.compute(nid, "Fin die width", "foil_w + 2 * die_side_mm", "mm", names={k: self.var(k) for k in ("foil_w", "die_side_mm")})
        elif name == "die_h":
            t.compute(nid, "Sub-die height", "subdie_h_mm", "mm", names={"subdie_h_mm": self.var("subdie_h_mm")})
        else:
            return super().var(name)
        return nid

    def size(self) -> dict:
        rules = mould_db.sizing_rules(PART_TYPE)
        need = [k for k, *_ in SIZING if k not in rules]
        if need:
            raise ValueError(f"Mould & die database → Sizing rules has no fin row for {', '.join(need)} (run the stage 57 seed).")
        self.sized = {"rules": rules}            # var() reads the sizing rules from here while the die is sized
        die_l, die_w = self.trace.value(self.var("die_l")), self.trace.value(self.var("die_w"))
        sets = sorted((b for b in self.db["mould_bases"] if b["part_type"] == PART_TYPE),
                      key=lambda b: (b["length_mm"] * b["width_mm"], b["cost"]))
        if not sets:
            raise ValueError("Mould & die database → Mould bases has no fin die set yet.")
        for b in sets:
            if b["max_insert_length_mm"] >= die_l and b["max_insert_width_mm"] >= die_w:
                return {"base": b, "base_turned": False, "layout": {"rows": 1, "cols": 1, "empty": 0}, "rules": rules,
                        "die": {"die_l": die_l, "die_w": die_w}, "warnings": [],
                        "sizing_rules_are_examples": any(r["is_example"] for r in rules.values())}
        big = sets[-1]
        raise ValueError(f"No fin die set in Mould bases takes a fin die of {die_l:.0f} × {die_w:.0f} mm (largest usable "
                         f"{big['max_insert_length_mm']:g} × {big['max_insert_width_mm']:g} mm). Add a bigger fin die set.")

    def base_label(self) -> str:
        b = self.sized["base"]
        return f"Fin die set {b['size_code']}"

    def piece_input(self, scope: str, var: str) -> str:
        if var in FIN_VARS or var in ("holes_per_stroke", "feed"):
            return self.var({"foil_t": "foil_t"}.get(var, var))
        raise ToolCostError(f"Formula input '{var}' of {scope} is not a fin die value.")

    def scope_names(self, scope: str) -> dict:
        names = {}
        for inp in (r for r in self.setup["formula_inputs"] if r["scope"] == scope):
            var, label = inp["variable"], inp["label"] or inp["variable"]
            if inp["source"] == "piece":
                names[var] = self.piece_input(scope, inp["item"])
            elif inp["source"] == "parameter":
                row = _param(inp["item"])
                names[var] = self.master(f"{scope}:in:{var}", label, row["value"], inp["unit"] or row["unit"] or "", "Parameters",
                                         f"{row['part_type']} / {inp['item']}",
                                         ref=_ref("master_data", "Parameters", {"part_type": row["part_type"], "parameter": inp["item"]}, "value"))
            else:
                raise ToolCostError(f"Formula input '{var}' of {scope}: source '{inp['source']}' is not used by the fin die force.")
        return names

    def trial(self) -> dict:
        """Die force (Cost formulas fin_force) → fin press: typed, else the smallest that takes force, foil width and die set."""
        t = self.trace
        try:
            force_node, _, _ = rate_engine.evaluate_scope(t, self.setup, FORCE_SCOPE, self.scope_names(FORCE_SCOPE), self.cur, self.as_of, inr=False)
        except (rate_engine.EngineError, formula.FormulaError) as exc:
            raise ToolCostError(str(exc)) from None
        force = t.value(force_node)
        process = _param("trial_machine_process")["value"]
        lines = press_rows()
        b = self.sized["base"]
        cands = []
        for m in self.machines.values():
            if m["process"] != process or m["machine_id"] not in lines:
                continue
            ln = lines[m["machine_id"]]
            why = []
            if (m["tonnage_t"] or 0) < force:
                why.append(f"{m['tonnage_t']:g} t < {force:.1f} t")
            if ln["max_foil_width_mm"] < self.foil_w:
                why.append(f"foil width {ln['max_foil_width_mm']:g} < {self.foil_w:g} mm")
            if m.get("length_mm") and m.get("width_mm") and (m["length_mm"] < b["length_mm"] or m["width_mm"] < b["width_mm"]):
                why.append(f"bed {m['length_mm']:g} × {m['width_mm']:g} mm < die set {b['length_mm']:g} × {b['width_mm']:g} mm")
            cands.append((m, ln, why))
        out = {"force_node": force_node, "force_t": force, "process": process, "machine": None, "line": None, "rejected": []}
        chosen = None
        want, how = self.s["press"], "your choice (Fin die spec)"
        if not want:
            want = default_press()
            how = "the default fin press (Fin presses → default press, else Parameters fin → default_fin_press)"
        if want and want != "auto":
            hit = next(((m, ln, why) for m, ln, why in cands if m["machine_id"] == want), None)
            if not hit:
                raise ToolCostError(f"Press '{want}' is not a fin press (Machines process '{process}' with a Fin presses row).")
            chosen = hit
            if hit[2]:
                self.sized["warnings"].append(f"Press {hit[0]['machine_id']} does not suit this die: {'; '.join(hit[2])}. "
                                              "Choose a bigger press or 'smallest that fits'.")
            spm = self.s.get("spm") or 0
            if spm and not hit[1]["spm_min"] <= spm <= hit[1]["spm_max"]:
                self.sized["warnings"].append(f"SPM {spm:g} is outside the {hit[0]['machine_id']} range "
                                              f"{hit[1]['spm_min']:g}-{hit[1]['spm_max']:g} SPM.")
        else:
            fits = sorted((c for c in cands if not c[2]), key=lambda c: (c[0]["tonnage_t"] or 0, c[1]["max_foil_width_mm"]))
            out["rejected"] = [f"{m['machine_id']}: {'; '.join(why)}" for m, _ln, why in cands if why]
            if fits:
                chosen = fits[0]
                how = (f"smallest '{process}' machine whose tonnage ≥ the die force, whose foil width (Fin presses) ≥ the strip "
                       "and whose bed takes the fin die set")
        if not chosen:
            mhr_node = self.miss("trial:machine", "Fin press", f"No fin press takes this die ({force:.1f} t, foil {self.foil_w:g} mm, die set "
                                 f"{b['length_mm']:g} × {b['width_mm']:g} mm): " + ("; ".join(out["rejected"]) or "no fin press in Machines")
                                 + ". Add a bigger fin press.", "t")
        else:
            m, ln, _ = chosen
            out["machine"], out["line"] = m, ln
            t.add_derived("trial:machine", f"Fin press: {m['machine_id']} · {m['name']}", m["tonnage_t"], "t", how,
                          {"die_force": force_node}, description=f"{m['tonnage_t']:g} t ≥ {force:.1f} t; foil width up to "
                          f"{ln['max_foil_width_mm']:g} mm ≥ {self.foil_w:g} mm; bed {m.get('length_mm') or 0:g} × {m.get('width_mm') or 0:g} mm; "
                          f"SPM {ln['spm_min']:g}-{ln['spm_max']:g}; die height {ln['die_height_min_mm']:g}-{ln['die_height_max_mm']:g} mm")
            h = b["stack_height_mm"]
            if not ln["die_height_min_mm"] <= h <= ln["die_height_max_mm"]:
                self.sized["warnings"].append(f"Die shut height ≈ {h:g} mm (die set) is outside the {m['machine_id']} die height "
                                              f"{ln['die_height_min_mm']:g}-{ln['die_height_max_mm']:g} mm: check the die design.")
            mhr_node = self.mhr(m["machine_id"])
        trial = next((p for p in self.db["tool_processes"] if p["cost_group"] == "trial"), None)
        if trial and trial["operators"]:
            crew = self.crew(trial | {"pricing": "labour_hour"}, "trial:crew", None)
        else:
            crew = self.master("trial:crew", "Try-out crew per hour", 0, self.money_unit("h"), "Mould & die database → Tool processes",
                               (trial or {}).get("code", "Tryout"), bool((trial or {}).get("is_example")))
        t.nodes[crew]["label"] = "Try-out crew per hour (operators × labour rate)"
        out |= {"mhr_node": mhr_node, "crew_node": crew}
        self.trial_out = out
        return out

    def run(self) -> dict:
        out = super().run()
        tr = self.trial_out
        out["trial"] |= {"line": tr["line"], "rejected": tr["rejected"]}
        out |= {"die": {"length_mm": self.trace.value("v:die_l"), "width_mm": self.trace.value("v:die_w"),
                        "stations": self.trace.value("v:stations"), "holes_per_stroke": self.trace.value(self.var("holes_per_stroke")),
                        "feed_mm": self.trace.value(self.var("feed")), "foil_width_mm": self.foil_w, "foil_width_note": self.foil_w_note},
                "pattern": self.pattern}
        return out


def die_cost(s: dict) -> dict:
    pattern = pattern_row(s["pattern"])
    mat = _density(s["material"])
    foil_w, _ = foil_width(s)
    feed = s["progressions"] * s["hole_pitch_mm"]
    stroke_g = foil_w * feed * s["foil_t_mm"] * float(mat["density_g_cm3"]) / 1000
    inp = ToolInput(part_type=PART_TYPE, cavities=1, part_length_mm=feed, part_width_mm=foil_w, part_height_mm=s["foil_t_mm"],
                    part_weight_g=stroke_g, material=s["material"], country=s["country"] or None, as_of=s.get("as_of") or None,
                    tools_count=s["tools_count"], warranty=s["warranty"], annual_volume=0, programme_years=s["programme_years"])
    try:
        return _FinDieRun(inp, s, pattern).run()
    except ToolCostError as exc:
        raise FinDieError(str(exc)) from None


# ---------------------------------------------------------------- part cost ----------

def part_cost(s: dict, die: dict) -> dict:
    from .piece_cost import graft
    setup = costing_setup.tables()
    country, cur, as_of = die["country"], die["currency"], die["as_of"]
    t = Trace(cur)
    mat = _density(s["material"])
    missing: list[str] = []
    die_root = graft(t, die, "die:")
    t.nodes[die_root]["label"] = "Cost of one fin die (die cost trace)"
    m, ln = die["trial"]["machine"], die["trial"].get("line")
    if not m:
        raise FinDieError("No fin press for this die, so no part cost: " + "; ".join(die["missing"]))
    spec_src = {"type": "user", "note": "Fin die spec (Fin dies page)"}

    def rate_node(nid, label, cat, item, money=True):
        try:
            r = rates.lookup(cat, item, country, as_of)
        except rates.RateMissing as exc:
            missing.append(str(exc))
            t.add_input(nid, label, 0, "", {"type": "missing", "note": str(exc)}, money=money)
            return nid
        t.add_rate(nid, label, r, money=money)
        return rate_engine._convert(t, nid, label, r["currency"], cur, as_of) if money else nid

    def embed(sub, prefix, label):
        root = graft(t, sub, prefix)
        t.nodes[root]["label"] = label
        return root

    try:
        mhr = embed(rate_engine.mhr(m["machine_id"], country, as_of), f"mhr:{m['machine_id']}:", f"MHR {m['machine_id']} · {m['name']}")
        grade = master_data.parameters(PART_TYPE).get("operator_grade") or "operator"
        lab = embed(rate_engine.labour_rate(grade, country, as_of), f"lab:{grade}:", f"Labour rate · {grade}")
    except (rates.RateError, rate_engine.EngineError, formula.FormulaError) as exc:
        raise FinDieError(f"Fin press MHR / labour rate: {exc}") from None
    pat = die["pattern"]
    values = {
        "die_rows": ("spec", s["die_rows"]), "progressions": ("spec", s["progressions"]), "row_pitch": ("spec", s["row_pitch_mm"]),
        "hole_pitch": ("spec", s["hole_pitch_mm"]), "hole_d": ("spec", s["hole_d_mm"]), "foil_t": ("spec", s["foil_t_mm"]),
        "fin_rows": ("spec", s["fin_rows"]), "fin_holes": ("spec", s["fin_holes"]), "fpi": ("spec", s["fpi"]),
        "pack_length": ("spec", s["pack_length_mm"]), "packs_per_year": ("spec", s["packs_per_year"]),
        "programme_years": ("spec", s["programme_years"]), "spm_typed": ("spec", s["spm"]),
        "foil_kg_per_ac_set": ("spec", s["foil_kg_per_ac_set"]),
    }
    names = {}
    for inp in (r for r in setup["formula_inputs"] if r["scope"] == PART_SCOPE):
        var, label, item = inp["variable"], inp["label"] or inp["variable"], inp["item"]
        nid = f"in:{var}"
        unit = (inp["unit"] or "").replace("{cur}", cur)
        if inp["source"] == "parameter":
            row = _param(item)
            t.add_input(nid, row["description"] or label, row["value"], unit or row["unit"] or "",
                        {"type": "master", "sheet": "Parameters", "row": f"{row['part_type']} / {item}", "is_example": True,
                         "ref": _ref("master_data", "Parameters", {"part_type": row["part_type"], "parameter": item}, "value")})
        elif inp["source"] == "rate":
            nid = rate_node(nid, label, inp["category"], item, bool(inp["is_money"]))
        elif item in values:
            t.add_input(nid, FIN_ITEMS[item][0], float(values[item][1]), FIN_ITEMS[item][1], spec_src)
        elif item == "holes_per_stroke":
            nid = "die:v:holes_per_stroke"
        elif item == "feed":
            nid = "die:v:feed"
        elif item == "foil_w":
            nid = "die:v:foil_w"
        elif item == "density":
            t.add_input(nid, f"Density of {s['material']}", float(mat["density_g_cm3"]), "g/cm³",
                        {"type": "master", "sheet": "Master data → Materials", "row": f"fin / {s['material']}", "is_example": True,
                         "ref": _ref("master_data", "Materials", {"part_type": PART_TYPE, "material": s["material"]}, "density_g_cm3")})
        elif item == "spm_factor":
            t.add_input(nid, f"Speed factor · {pat['name']}", float(pat["spm_factor"]), "×",
                        {"type": "master", "sheet": "Mould & die database → Fin patterns", "row": pat["pattern"], "is_example": bool(pat["is_example"]),
                         "ref": _ref("mould_db", "fin_patterns", {"pattern": pat["pattern"]}, "spm_factor")})
        elif item == "press_spm_max":
            t.add_input(nid, f"SPM max · {m['machine_id']}", float(ln["spm_max"]), "strokes/min",
                        {"type": "master", "sheet": "Mould & die database → Fin presses", "row": m["machine_id"], "is_example": bool(ln["is_example"]),
                         "ref": _ref("mould_db", "fin_presses", {"machine_id": m["machine_id"]}, "spm_max")})
        elif item == "rm_rate":
            nid = rate_node(nid, f"Foil rate · {s['material']}", "material", s["material"])
        elif item == "scrap_rate":
            nid = rate_node(nid, f"Scrap value · {s['material']}", "material_scrap", s["material"])
        elif item == "mhr":
            nid = mhr
        elif item == "labour_rate":
            nid = lab
        elif item == "die_cost":
            nid = die_root
        else:
            raise FinDieError(f"Formula input '{var}' of {PART_SCOPE}: '{item}' is not a fin engine value.")
        names[var] = nid
    try:
        result, _comp, order = rate_engine.evaluate_scope(t, setup, PART_SCOPE, names, cur, as_of)
    except (rate_engine.EngineError, formula.FormulaError) as exc:
        raise FinDieError(str(exc)) from None
    out = t.to_dict(result)
    fx = t.value(rate_engine.fx_to_inr(t, cur, as_of))
    val = lambda n: t.value(f"calc:{n}") if f"calc:{n}" in t.nodes else None
    out |= {"country": country, "currency": cur, "as_of": as_of, "value": t.value(result), "value_inr": t.value("result:inr"),
            "per_fin": val("cost_per_fin"), "per_kg": val("cost_per_kg"), "fx_inr": fx,
            "per_fin_inr": (val("cost_per_fin") or 0) * fx, "per_kg_inr": (val("cost_per_kg") or 0) * fx,
            "steps": [{"name": r["name"], "label": r["label"], "node": f"calc:{r['name']}", "is_result": bool(r["is_result"])} for r in order],
            "press": m["machine_id"], "missing": missing}
    out["example"] = examples(out)
    return out


def run(spec: dict | None) -> dict:
    """Die cost and fin part cost of a fin spec, both traced."""
    s = normalise(spec)
    die = die_cost(s)
    part = part_cost(s, die)
    fx = part["fx_inr"]
    summary = {"die_cost_inr": die["value_inr"], "die_capex_inr": die["capex_inr"], "pack_cost_inr": part["value_inr"],
               "per_fin_inr": part["per_fin_inr"], "per_kg_inr": part["per_kg_inr"], "press": part["press"],
               "country": part["country"], "currency": part["currency"], "as_of": part["as_of"], "fx_inr": fx,
               "example": bool(die["example"]["any"] or part["example"]["any"])}
    return {"spec": s, "die": die, "part": part, "summary": summary}


def options() -> dict:
    """What the Fin dies page offers: patterns, presses, foils, countries and the default spec."""
    md = master_data.tables()
    cs = costing_setup.tables()
    lines = press_rows()
    return {"spec": SPEC, "default": default_spec(), "default_press": default_press(), "patterns": mould_db.tables()["fin_patterns"],
            "presses": [m | {"line": lines[m["machine_id"]]} for m in cs["machines"] if m["machine_id"] in lines],
            "materials": [r["material"] for r in md["Materials"] if r["part_type"] == PART_TYPE],
            "countries": [{"code": c["code"], "name": c.get("name") or c["code"], "currency": c["currency"]} for c in cs["countries"]]}


# ---------------------------------------------------------------- saved fin dies (your data) ----------

def _db():
    from . import projects_db as db
    return db


def list_all(project_id: int | None = None) -> list[dict]:
    db = _db()
    q = db.fin_dies.select().order_by(db.fin_dies.c.id.desc())
    if project_id:
        q = q.where(db.fin_dies.c.project_id == project_id)
    with db.engine().connect() as con:
        return [dict(r._mapping) for r in con.execute(q)]


def get(fid: int) -> dict:
    db = _db()
    with db.engine().connect() as con:
        r = con.execute(db.fin_dies.select().where(db.fin_dies.c.id == fid)).first()
    if not r:
        raise FinDieError(f"Fin die {fid} not found.")
    return dict(r._mapping)


def save(data: dict, fid: int | None = None, user: str = "") -> dict:
    db = _db()
    name = (data.get("name") or "").strip()
    if not name:
        raise FinDieError("Give the fin die a name.")
    spec = normalise(data.get("spec"))
    row = {"name": name, "project_id": data.get("project_id") or None, "spec": spec}
    for k in ("part_file", "read"):                     # stage 58: part file and what was read from it
        if k in data:
            row[k] = data[k]
    with db.engine().begin() as con:
        if fid is None:
            fid = con.execute(db.fin_dies.insert().values(**row, created_by=user)).inserted_primary_key[0]
        else:
            get(fid)
            con.execute(db.fin_dies.update().where(db.fin_dies.c.id == fid).values(**row))
    return get(fid)


def calculate(fid: int) -> dict:
    """Cost a saved fin die and keep the summary on it."""
    db = _db()
    rec = get(fid)
    res = run(rec["spec"])
    with db.engine().begin() as con:
        con.execute(db.fin_dies.update().where(db.fin_dies.c.id == fid).values(result=res["summary"]))
    return res | {"record": get(fid)}


def delete(fid: int) -> None:
    db = _db()
    get(fid)
    with db.engine().begin() as con:
        con.execute(db.fin_dies.delete().where(db.fin_dies.c.id == fid))


# ---------------------------------------------------------------- downloads ----------

def _spec_rows(s: dict) -> list[list]:
    rows = [["Fin pattern", s["pattern"], ""], ["Foil", s["material"], ""]]
    rows += [[label, s[k], unit] for k, (label, unit, *_r) in SPEC.items()]
    return rows + [["Country", s["country"] or "default", ""], ["Press", {"": "default press", "auto": "smallest that fits"}.get(s["press"], s["press"]), ""]]


def to_excel(res: dict, name: str = "Fin die") -> bytes:
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from .table_set import HEADER_FILL
    from .trace import source_text
    d, p, sm = res["die"], res["part"], res["summary"]
    dn, pn = d["nodes"], p["nodes"]
    ex = "EXAMPLE values in use: not for negotiation" if sm["example"] else "no"
    sheets = [
        ("Summary", ["Item", sm["currency"], "INR"], [
            ["Fin die", name, ""], ["Country / month", f"{sm['country']} / {sm['as_of']}", ""], ["Fin press", sm["press"], ""],
            ["Fin die cost (one die)", d["value"], d["value_inr"]], ["Fin die CAPEX (dies over the programme)", d["capex"], d["capex_inr"]],
            ["Fin pack cost", p["value"], p["value_inr"]], ["Cost per fin", p["per_fin"], p["per_fin_inr"]],
            ["Cost per kg of fin", p["per_kg"], p["per_kg_inr"]], ["Example values", ex, ""]]),
        ("Fin spec", ["Item", "Value", "Unit"], _spec_rows(res["spec"])),
        ("Die BOM", ["Element", "Category", "Qty", "Grade", "Make", "Weight each kg", "Steel", "Bought-out", "Process", "Hours", "Total"],
         [[l["element"], l["category"], l["quantity"], l["grade"], l["make"], l["weight_each_kg"], dn[l["nodes"]["mat"]]["value"] if l["nodes"].get("mat") else 0,
           dn[l["nodes"]["bo"]]["value"] if l["nodes"].get("bo") else 0, l["process"], dn[l["nodes"]["hours"]]["value"] if l["nodes"].get("hours") else 0,
           l["total"]] for l in d["lines"]]),
        ("Die cost steps", ["Step", "Formula", "Value", "Unit"],
         [[dn[x["node"]]["label"], dn[x["node"]].get("formula", ""), dn[x["node"]]["value"], dn[x["node"]]["unit"]] for x in d["steps"]]),
        ("Part cost steps", ["Step", "Formula", "Value", "Unit"],
         [[pn[x["node"]]["label"], pn[x["node"]].get("formula", ""), pn[x["node"]]["value"], pn[x["node"]]["unit"]] for x in p["steps"]]),
        ("Part inputs", ["Input", "Value", "Unit", "Source"], [[pn[k]["label"], pn[k]["value"], pn[k]["unit"], source_text(pn[k])] for k in pn if k.startswith("in:")]),
        ("Rates used", ["Rate #", "Category", "Item", "Country", "Month", "Value", "Unit", "Example"],
         [[x["id"], x["category"], x["item"], x["country"], x["month"], x["value"], x["unit"], "EXAMPLE" if x.get("is_example") else ""]
          for x in {r["id"]: r for r in d["rates_used"] + p["rates_used"]}.values()]),
        ("Warnings", ["Warning"], [[w] for w in d["warnings"] + d["missing"] + p["missing"]] or [["none"]]),
    ]
    wb = Workbook()
    for i, (title, head, rows) in enumerate(sheets):
        ws = wb.active if i == 0 else wb.create_sheet()
        ws.title = title
        ws.append(head)
        for c in ws[1]:
            c.font, c.fill = Font(bold=True, color="FFFFFF"), HEADER_FILL
        for r in rows:
            ws.append(r)
        ws.column_dimensions["A"].width = 44
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def to_pdf(res: dict, name: str = "Fin die") -> bytes:
    import io
    from datetime import date
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    from .pdf_report import _example_banner, _table, _theme
    theme, ss = _theme(), getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], textColor=theme["ink"], fontSize=18, alignment=0, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=theme["ink"], fontSize=11, spaceBefore=8, spaceAfter=4)
    note = ParagraphStyle("n", parent=ss["Normal"], textColor=theme["grey"], fontSize=7.5)
    cell = ParagraphStyle("c", parent=ss["Normal"], fontSize=7.5, leading=9)
    wrap = lambda x: Paragraph(str(x if x is not None else "").replace("&", "&amp;").replace("<", "&lt;"), cell)
    f = lambda v: "—" if v is None else f"{v:,.2f}"
    d, p, sm = res["die"], res["part"], res["summary"]
    dn, pn = d["nodes"], p["nodes"]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=14 * mm, rightMargin=14 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
                            title=f"Design to Cost — fin die {name}", author="Design to Cost")
    sp = res["spec"]
    story = [Paragraph("FIN DIE AND FIN PART COST", ParagraphStyle("k", parent=ss["Normal"], textColor=theme["brand"], fontSize=8)),
             Paragraph(name, h1),
             Paragraph(f"Ø{sp['tube_od_mm']:g} × {sp['die_rows']}R × {sp['progressions']}P · {sp['row_pitch_mm']:g} × {sp['hole_pitch_mm']:g} mm · "
                       f"{sp['pattern']} · {sp['material']} {sp['foil_t_mm']:g} mm · country {sm['country']} · month {sm['as_of']} · "
                       f"press {sm['press']} · {date.today().isoformat()}", note)]
    if sm["example"]:
        story += [Spacer(1, 2 * mm), _example_banner(ss)]
    for w in d["warnings"] + d["missing"] + p["missing"]:
        story.append(Paragraph(f"<font color='#b45309'>■ {w}</font>", note))
    story += [Paragraph("Result", h2),
              _table([["", sm["currency"], "INR"], ["Fin die cost (one die)", f(d["value"]), f(d["value_inr"])],
                      ["Fin die CAPEX", f(d["capex"]), f(d["capex_inr"])], ["Fin pack cost", f(p["value"]), f(p["value_inr"])],
                      ["Cost per fin", f"{p['per_fin']:,.4f}", f"{p['per_fin_inr']:,.4f}"], ["Cost per kg of fin", f(p["per_kg"]), f(p["per_kg_inr"])]],
                     theme, [80 * mm, 40 * mm, 40 * mm]),
              Paragraph("Fin die BOM", h2),
              _table([["Element", "Qty", "Grade", "Make", "Total"]] + [[wrap(l["element"]), f"{l['quantity']:g}", wrap(l["grade"]), wrap(l["make"]), f(l["total"])]
                                                                      for l in d["lines"]], theme, [95 * mm, 20 * mm, 70 * mm, 50 * mm, 30 * mm]),
              Paragraph("Fin die cost steps", h2),
              _table([["Step", "Formula", "Value", "Unit"]] + [[wrap(dn[x["node"]]["label"]), wrap(dn[x["node"]].get("formula", "")), f(dn[x["node"]]["value"]), dn[x["node"]]["unit"]]
                                                              for x in d["steps"]], theme, [70 * mm, 120 * mm, 35 * mm, 25 * mm]),
              Paragraph("Fin part cost steps (per pack)", h2),
              _table([["Step", "Formula", "Value", "Unit"]] + [[wrap(pn[x["node"]]["label"]), wrap(pn[x["node"]].get("formula", "")), f"{pn[x['node']]['value']:,.4f}", pn[x["node"]]["unit"]]
                                                              for x in p["steps"]], theme, [70 * mm, 120 * mm, 35 * mm, 25 * mm])]
    doc.build(story)
    return buf.getvalue()
