"""Traceable calculations: every value knows how it was made.

A Trace is a set of nodes. Each node is either
    an input      value + its source (rate version, machine row, user input, ...)
    a calculated  value + the formula + the ids of the nodes it used
The browser shows any node in the traceability panel and lets you click
through to its inputs.
"""

from __future__ import annotations

from . import formula


class Trace:
    def __init__(self, currency: str = ""):
        self.nodes: dict[str, dict] = {}
        self.currency = currency
        self.rates_used: dict[int, dict] = {}

    def value(self, node_id: str) -> float:
        return self.nodes[node_id]["value"]

    def add_input(self, node_id, label, value, unit="", source=None, money=False):
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
        return value

    def to_dict(self, root: str) -> dict:
        return {"root": root, "currency": self.currency, "nodes": self.nodes,
                "rates_used": sorted(self.rates_used.values(), key=lambda r: r["id"])}
