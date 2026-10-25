"""Traceable calculations: every value knows how it was made.

A Trace is a set of nodes. Each node is either
    an input      value + its source (rate version, machine row, user input, ...)
    a calculated  value + the formula + the ids of the nodes it used
The browser shows any node in the traceability panel and lets you click
through to its inputs.
"""

from __future__ import annotations

from . import formula

# Shown on screen and in every Excel / PDF export of a cost that uses a rate still marked EXAMPLE.
EXAMPLE_WARNING = "Uses example rates – not for negotiation"


class Trace:
    def __init__(self, currency: str = "", overrides: dict | None = None):
        self.nodes: dict[str, dict] = {}
        self.currency = currency
        self.rates_used: dict[int, dict] = {}
        # Your changes for one part: {node id: {"value": number} or {"formula": text}, "note", "by", "at"}.
        # The value / formula replaces the master-data or rate-library one in this calculation only, and the node
        # keeps what it replaced ("was"), so the panel shows both and can reset it.
        self.overrides = overrides or {}

    def value(self, node_id: str) -> float:
        return self.nodes[node_id]["value"]

    def add_input(self, node_id, label, value, unit="", source=None, money=False):
        ov = self.overrides.get(node_id)
        if ov and ov.get("value") is not None:
            source = {"type": "override", "note": ov.get("note") or "Changed for this part", "by": ov.get("by", ""),
                      "at": ov.get("at", ""), "was": value, "was_source": source or {"type": "unknown"}}
            value = float(ov["value"])
        self.nodes[node_id] = {"id": node_id, "label": label, "value": value, "unit": unit, "money": money,
                               "kind": "input", "source": source or {"type": "unknown"}}
        rate = (source or {}).get("rate")
        if rate:
            self.rates_used[rate["id"]] = rate
        return value

    def add_rate(self, node_id, label, rate: dict, value=None, unit=None, money=False):
        """An input taken from a rate-library version."""
        src = {"type": "rate", "rate": rate}
        return self.add_input(node_id, label, rate["value"] if value is None else value,
                              rate["unit"] if unit is None else unit, src, money)

    def compute(self, node_id, label, text, unit="", money=False, description="", names=None):
        """Evaluate a formula whose names refer to existing node ids (or `names` maps name -> node id)."""
        names = names or {}
        ov = self.overrides.get(node_id) or {}
        was_formula = None
        if ov.get("formula"):
            was_formula, text = text, ov["formula"]
        used = formula.names(text)
        env, inputs = {}, []
        for n in sorted(used):
            nid = names.get(n, n)
            if nid not in self.nodes:
                raise formula.FormulaError(f"'{label}' uses '{n}', which has no value")
            env[n] = self.nodes[nid]["value"]
            inputs.append({"name": n, "node": nid})
        value = formula.evaluate(text, env)
        self.nodes[node_id] = {"id": node_id, "label": label, "value": value, "unit": unit, "money": money,
                               "kind": "calculated", "formula": text, "inputs": inputs, "description": description}
        if was_formula is not None or ov.get("value") is not None:
            self.nodes[node_id]["override"] = {"note": ov.get("note") or "Changed for this part", "by": ov.get("by", ""),
                                               "at": ov.get("at", ""), "was_formula": was_formula, "was_value": value}
            if ov.get("value") is not None:
                value = self.nodes[node_id]["value"] = float(ov["value"])
        return value

    def add_derived(self, node_id, label, value, unit, method, inputs: dict, description=""):
        """A value worked out by a search in code (e.g. sheet nesting) rather than one formula.

        `method` says in words how it is found; `inputs` maps a name to the node it used.
        """
        self.nodes[node_id] = {"id": node_id, "label": label, "value": value, "unit": unit, "money": False,
                               "kind": "calculated", "formula": method, "method": True,
                               "inputs": [{"name": n, "node": nid} for n, nid in inputs.items()],
                               "description": description}
        return value

    def to_dict(self, root: str) -> dict:
        return {"root": root, "currency": self.currency, "nodes": self.nodes,
                "rates_used": sorted(self.rates_used.values(), key=lambda r: r["id"])}


def source_text(node: dict) -> str:
    """Plain-text 'comes from' of a node, for Excel and PDF exports (the browser panel has its own)."""
    s = node.get("source") or {}
    t = s.get("type")
    if t == "rate":
        r = s["rate"]
        return (f"Rate library #{r['id']} · {r['category']} / {r['item']}" + (f" · {r['country']}" if r["country"] else "")
                + f" · {r['month']} · {r['status']}" + (" · EXAMPLE" if r.get("is_example") else ""))
    if t == "machine":
        return f"Master data → Machines · {s.get('machine_id')} · {s.get('field')}"
    if t == "master":
        return f"Master data → {s.get('sheet')} · {s.get('row')}" + (" · EXAMPLE" if s.get("is_example") else "")
    if t == "cad":
        return f"3D file {s.get('file', '')}" + (f" · rev {s['rev']}" if s.get("rev") else "") + (f" · {s['note']}" if s.get("note") else "")
    if t == "user":
        return "Your input" + (f" · {s['note']}" if s.get("note") else "")
    if t == "register":
        return f"Part register · {s.get('note', '')}"
    if t == "missing":
        return f"MISSING · {s.get('note', '')}"
    if t == "base":
        return s.get("note", "")
    return "Calculated" if node.get("kind") == "calculated" else "—"
