"""Safe evaluation of the small formulas stored in the mould database.

A rule is a one-line Excel-like expression, for example
    max(4, ceil(cavities * projected_area_cm2 / 8))
    cavities if hot_runner else 0
Only arithmetic, comparisons, 'a if c else b', and/or/not, the functions
below and the variables in VARIABLE_HELP are allowed, so a rule can never
run other code.
"""

from __future__ import annotations

import ast
import math
import operator

FUNCTIONS = {
    "ceil": math.ceil, "floor": math.floor, "round": round,
    "min": min, "max": max, "abs": abs, "sqrt": math.sqrt, "log": math.log, "exp": math.exp,
}

VARIABLE_HELP = {
    "cavities": "Cavities per mould / die (from Stage C)",
    "layout_rows": "Rows of cavities in the layout",
    "layout_cols": "Columns of cavities in the layout",
    "part_l": "Part length across the parting plane (mm)",
    "part_w": "Part width across the parting plane (mm)",
    "part_h": "Part height along the opening direction (mm)",
    "projected_area_cm2": "Projected area of one part (cm²)",
    "part_weight_g": "Net weight of one part (g)",
    "insert_each_l": "Core/cavity insert length per cavity = part_l + 2 × insert_wall_mm",
    "insert_each_w": "Core/cavity insert width per cavity = part_w + 2 × insert_wall_mm",
    "insert_half_h": "Insert height per half (core or cavity) = part_h / 2 + insert_backing_mm",
    "pocket_l": "Insert pocket length for all cavities (mm)",
    "pocket_w": "Insert pocket width for all cavities (mm)",
    "base_l": "Selected mould base length (mm)",
    "base_w": "Selected mould base width (mm)",
    "base_stack_h": "Selected mould base stack height (mm)",
    "base_weight_kg": "Selected mould base weight (kg)",
    "hot_runner": "1 if a hot runner is used, else 0",
    "slides_per_cavity": "Slides (side actions) per cavity",
    "lifters_per_cavity": "Lifters per cavity",
    "inserts_per_cavity": "Extra small inserts per cavity",
    "density": "Density of the row's material (g/cm³), for weight rules",
    "part_volume_cm3": "Volume of one part (cm³), from the 3D file",
    "part_surface_cm2": "Surface area of one part (cm²), from the 3D file: the moulding surface of core + cavity",
    "part_box_cm3": "Bounding box of one part = part_l × part_w × part_h ÷ 1000 (cm³): basis of the steel removed per cavity",
    "annual_volume": "Annual volume of the part (parts/yr)",
    "programme_years": "Programme life (years)",
    "programme_shots": "Shots / strokes per tool over the programme = annual_volume × programme_years ÷ cavities",
    # sheet-metal dies (roadmap stage 23)
    "t": "Sheet-metal dies: sheet thickness (mm)",
    "blank_l": "Sheet-metal dies: blank length (mm)",
    "blank_w": "Sheet-metal dies: blank width (mm)",
    "blank_perimeter": "Sheet-metal dies: blank perimeter (mm)",
    "hole_count": "Sheet-metal dies: pierced holes",
    "hole_perimeter": "Sheet-metal dies: total hole perimeter (mm)",
    "bends": "Sheet-metal dies: bends",
    "bend_len": "Sheet-metal dies: total bend length (mm)",
    "draw_depth": "Sheet-metal dies: draw depth (mm)",
    "draw_dia": "Sheet-metal dies: equivalent draw punch diameter (mm)",
    "die_ops": "Sheet-metal dies: operations in this die",
    "progressive": "Sheet-metal dies: 1 for a progressive die, else 0",
    "stations": "Sheet-metal dies: stations (progressive), else 1",
    "pitch": "Sheet-metal dies: pitch, feed per stroke (mm)",
    "strip_w": "Sheet-metal dies: strip width (mm)",
    "die_force_t": "Sheet-metal dies: force of this die (t)",
    "work_l": "Sheet-metal dies: work area length (blank, or strip for a progressive die) (mm)",
    "work_w": "Sheet-metal dies: work area width (mm)",
    "die_l": "Sheet-metal dies: die plate length = work_l + 2 × die_wall_mm",
    "die_w": "Sheet-metal dies: die plate width = work_w + 2 × die_wall_mm",
    "die_h": "Sheet-metal dies: die plate height = max(die_plate_min_mm, die_plate_t_factor × t)",
    "cut_len": "Sheet-metal dies: cutting length in this die (blank / trim outline + hole perimeters) (mm)",
    "punches": "Sheet-metal dies: cutting punches in this die",
    "op_blank": "Sheet-metal dies: 1 when the die blanks (op_<code> for every Sheet operation code)",
    "op_pierce": "Sheet-metal dies: piercing operations in the die",
    "op_bend": "Sheet-metal dies: bending operations in the die",
    "op_draw": "Sheet-metal dies: drawing operations in the die",
    "op_trim": "Sheet-metal dies: trimming operations in the die",
}
# The rules may also use the names in Mould & die database → Process time parameters of the part type
# (removal rates, set-up hours, shares), e.g. setup_h + part_box_cm3 / 2 / cnc_rough_cm3_per_h.

_BINOPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_CMPOPS = {
    ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt,
    ast.GtE: operator.ge, ast.Eq: operator.eq, ast.NotEq: operator.ne,
}


class FormulaError(ValueError):
    pass


def _eval(node, env):
    if isinstance(node, ast.Expression):
        return _eval(node.body, env)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in env:
            return env[node.id]
        allowed = [k for k in env if not k.startswith("_")]
        raise FormulaError(f"unknown name '{node.id}'. Allowed: {', '.join(allowed)}")
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        if isinstance(node.op, ast.Pow):
            exp = _eval(node.right, env)
            if abs(exp) > 6:
                raise FormulaError("powers above 6 are not allowed")
            return _eval(node.left, env) ** exp
        return _BINOPS[type(node.op)](_eval(node.left, env), _eval(node.right, env))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd, ast.Not)):
        v = _eval(node.operand, env)
        return -v if isinstance(node.op, ast.USub) else +v if isinstance(node.op, ast.UAdd) else int(not v)
    if isinstance(node, ast.BoolOp):
        values = [_eval(v, env) for v in node.values]
        return int(all(values)) if isinstance(node.op, ast.And) else int(any(values))
    if isinstance(node, ast.Compare):
        left = _eval(node.left, env)
        for op, comp in zip(node.ops, node.comparators):
            if type(op) not in _CMPOPS:
                raise FormulaError("unsupported comparison")
            right = _eval(comp, env)
            if not _CMPOPS[type(op)](left, right):
                return 0
            left = right
        return 1
    if isinstance(node, ast.IfExp):
        return _eval(node.body, env) if _eval(node.test, env) else _eval(node.orelse, env)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCTIONS and not node.keywords:
        return FUNCTIONS[node.func.id](*[_eval(a, env) for a in node.args])
    raise FormulaError("only numbers, variables, + - * / ( ), comparisons, 'if ... else', and "
                       f"{', '.join(FUNCTIONS)} are allowed")


def _parse(text: str):
    text = str(text).strip().lstrip("=")  # allow an Excel-style leading '='
    if not text:
        raise FormulaError("is empty")
    if len(text) > 500:
        raise FormulaError("is too long (max 500 characters)")
    try:
        return ast.parse(text, mode="eval")
    except SyntaxError:
        raise FormulaError(f"'{text}' is not a valid formula") from None


def evaluate(text: str, env: dict) -> float:
    try:
        value = _eval(_parse(text), env)
    except FormulaError:
        raise
    except ZeroDivisionError:
        raise FormulaError(f"'{text}' divides by zero") from None
    except (TypeError, ValueError, OverflowError) as exc:
        raise FormulaError(f"'{text}': {exc}") from None
    return float(value)


# Typical values used only to check a rule when it is saved.
SAMPLE = {name: 1.0 for name in VARIABLE_HELP} | {
    "cavities": 4, "layout_rows": 2, "layout_cols": 2, "part_l": 100, "part_w": 60, "part_h": 30,
    "projected_area_cm2": 60, "part_weight_g": 50, "insert_each_l": 150, "insert_each_w": 110,
    "insert_half_h": 40, "pocket_l": 310, "pocket_w": 230, "base_l": 400, "base_w": 350,
    "base_stack_h": 350, "base_weight_kg": 300, "hot_runner": 1, "density": 7.85,
    "part_volume_cm3": 40, "part_surface_cm2": 400, "part_box_cm3": 180,
    "annual_volume": 100000, "programme_years": 5, "programme_shots": 125000, "t": 2, "blank_l": 120, "blank_w": 60,
    "blank_perimeter": 360, "hole_count": 2, "hole_perimeter": 60, "bend_len": 60, "die_l": 200, "die_w": 140,
    "die_h": 25, "work_l": 120, "work_w": 60, "cut_len": 420, "punches": 3, "die_force_t": 40, "pitch": 125, "strip_w": 70,
}


def names(text: str) -> set[str]:
    """Variable names a formula uses (function names excluded)."""
    tree = _parse(text)
    funcs = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id not in funcs}


def check(text: str) -> None:
    evaluate(text, SAMPLE)
