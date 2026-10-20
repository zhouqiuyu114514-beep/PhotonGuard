"""Read-only, bounded AST recognition of an explicit two-simulation Meep recipe.

This is a deterministic parser, not Python execution or an AI intent extractor.
An accepted input supplies a canonical recipe representation, not a certificate
of equivalence for an arbitrary program. See docs/IMPORT_LIMITATIONS.md.
"""
from __future__ import annotations

import ast
import base64
from dataclasses import dataclass
import hashlib
import io
import math
import tokenize
from pathlib import Path

from .core import candidate_problem, digest, task_problem

IMPORTER = "meep-film1d-ast-v1"
MAX_BYTES = 131072
MAX_NODES = 12000
MAX_DEPTH = 64
MAX_MAGNITUDE = 1e12
MAX_BINDINGS = 512
MAX_VALUE_LOCATIONS = 256
CLAIM = ("Canonical film1d-v1 recipe extracted by a deterministic read-only AST parser. "
         "The supplied Python is never executed. Verification results apply to the "
         "canonical recipe and locked task, not arbitrary script behavior or its postprocessing.")


class Unsupported(ValueError):
    def __init__(self, message, node=None, field="script"):
        super().__init__(message)
        self.node = node
        self.field = field


def location(node):
    if node is None:
        return None
    return {"line": node.lineno, "column_utf8": node.col_offset,
            "end_line": node.end_lineno, "end_column_utf8": node.end_col_offset}


@dataclass
class Value:
    kind: str
    data: object
    locations: list


def unique_locations(items, node=None):
    result = []; seen = set()
    for item in items:
        if item is None:
            continue
        key = (item["line"], item["column_utf8"], item["end_line"], item["end_column_utf8"])
        if key not in seen:
            if len(result) >= MAX_VALUE_LOCATIONS:
                raise Unsupported("Expression exceeds the 256 source-location dependency budget", node)
            seen.add(key); result.append(item)
    return result


def locations(node, *values):
    return unique_locations([location(node)] + [x for v in values for x in v.locations], node)


def plain(value):
    if isinstance(value, Value):
        return plain(value.data)
    if isinstance(value, list):
        return [plain(x) for x in value]
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items() if not k.startswith("_")}
    return value


def number(v):
    if v.kind != "number":
        raise Unsupported("Expected a finite numeric expression")
    return v.data


def same(a, b):
    if type(a) in (int, float) and type(b) in (int, float):
        return math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(same(a[k], b[k]) for k in a)
    return type(a) is type(b) and a == b


class Reader:
    def __init__(self, source):
        self.source = source
        self.bindings = {}
        self.alias = None
        self.sims = []
        self.current_node = None
        self.current_field = "script"
        self.numeric_normalizations = []

    def fail(self, reason, node=None, field=None):
        raise Unsupported(reason, node or self.current_node, field or self.current_field)

    def finite(self, value, node, *deps):
        if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > MAX_MAGNITUDE:
            self.fail("Numeric value must be finite with absolute value <= 1e12", node)
        return Value("number", value, locations(node, *deps))

    def read(self, tree):
        for i, statement in enumerate(tree.body):
            self.current_node = statement
            self.current_field = "script"
            if i == 0 and isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str):
                continue  # Inert module docstring. Never used as task intent.
            if isinstance(statement, ast.Import):
                if self.alias is not None or self.bindings or self.sims or len(statement.names) != 1:
                    self.fail("Exactly one initial 'import meep as mp' is supported")
                entry = statement.names[0]
                if entry.name != "meep" or not entry.asname or entry.asname.startswith("_"):
                    self.fail("Only a single explicit aliased Meep import is supported")
                self.alias = entry.asname
                continue
            if self.alias is None:
                self.fail("An explicit aliased Meep import must precede recipe statements")
            if isinstance(statement, ast.Assign):
                if len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name):
                    self.fail("Only single-name assignments are supported")
                if len(self.bindings) >= MAX_BINDINGS:
                    self.fail("Script exceeds the 512 assignment binding limit")
                name = statement.targets[0].id
                self.current_field = "bindings." + name
                if name in self.bindings or name == self.alias or name.startswith("_"):
                    self.fail("Names cannot be rebound, shadow Meep, or begin with underscore")
                value = self.expr(statement.value)
                if value.kind == "none":
                    self.fail("State-changing methods cannot be assigned")
                self.bindings[name] = value
            elif isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
                value = self.expr(statement.value)
                if value.kind != "none":
                    self.fail("Recipe objects and readouts must be assigned to explicit names")
            else:
                self.fail("Unsupported statement: " + type(statement).__name__)
        if self.alias is None:
            self.fail("Missing aliased Meep import")

    def expr(self, node):
        if isinstance(node, ast.Constant):
            if type(node.value) is bool:
                return Value("bool", node.value, locations(node))
            return self.finite(node.value, node)
        if isinstance(node, ast.Name):
            if node.id not in self.bindings:
                self.fail("Unresolved name: " + node.id, node)
            v = self.bindings[node.id]
            return Value(v.kind, v.data, locations(node, v))
        if isinstance(node, ast.List):
            if len(node.elts) > 201:
                self.fail("Recipe lists contain at most 201 values", node)
            vals = [self.expr(x) for x in node.elts]
            if vals and all(v.kind == 'number' for v in vals):
                return Value('list', vals, locations(node, *vals))
            if len(vals) > 8:
                self.fail("Recipe lists contain at most eight objects", node)
            if any(v.kind not in {"PML", "Source", "Block"} for v in vals):
                self.fail("Only flat lists of PML, Source or Block recipe objects are supported", node)
            return Value("list", vals, locations(node, *vals))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            v = self.expr(node.operand)
            return self.finite(number(v) * (-1 if isinstance(node.op, ast.USub) else 1), node, v)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
            a, b = self.expr(node.left), self.expr(node.right)
            x, y = number(a), number(b)
            if isinstance(node.op, ast.Pow) and (abs(y) > 16 or (x < 0 and int(y) != y)):
                self.fail("Power requires a real result and an exponent in [-16,16]", node)
            try:
                if isinstance(node.op, ast.Add): out = x + y
                elif isinstance(node.op, ast.Sub): out = x - y
                elif isinstance(node.op, ast.Mult): out = x * y
                elif isinstance(node.op, ast.Div): out = x / y
                else: out = x ** y
            except (ArithmeticError, ValueError):
                self.fail("Undefined or overflowing constant expression", node)
            return self.finite(out, node, a, b)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == self.alias and node.attr in {"inf", "Ex", "Z"}:
            # Infinity is an enum sentinel, allowed only for transverse block sizes.
            return Value("enum", "mp." + node.attr, locations(node))
        if isinstance(node, ast.Call):
            return self.call(node)
        self.fail("Unsupported expression: " + type(node).__name__, node)

    def signature(self, node, positional, required):
        if any(isinstance(x, ast.Starred) for x in node.args) or any(k.arg is None for k in node.keywords):
            self.fail("Starred and expanded arguments are unsupported", node)
        if len(node.args) != len(positional):
            self.fail("Expected exactly these positional arguments: " + str(positional), node)
        keys = [k.arg for k in node.keywords]
        if len(keys) != len(set(keys)) or set(keys) != set(required):
            self.fail("Expected exactly these keyword arguments: " + str(sorted(required)), node)
        return {**{k: self.expr(v) for k, v in zip(positional, node.args)},
                **{k.arg: self.expr(k.value) for k in node.keywords}}

    def require(self, condition, message, node):
        if not condition:
            self.fail(message, node)

    def call(self, node):
        if not isinstance(node.func, ast.Attribute) or not isinstance(node.func.value, ast.Name):
            self.fail("Only declared Meep constructors and tracked simulation methods are allowed", node)
        owner, name = node.func.value.id, node.func.attr
        if owner == self.alias:
            return self.meep_call(name, node)
        sim = self.bindings.get(owner)
        if not sim or sim.kind != "simulation":
            self.fail("Method owner is not a tracked simulation", node)
        return self.sim_call(sim, name, node)

    def meep_call(self, name, node):
        signatures = {
            "Vector3": (("x", "y", "z"), ()),
            "Medium": ((), ("index",) if {k.arg for k in node.keywords} == {"index"} else ("epsilon",)),
            "Block": ((), ("size", "center", "material")),
            "GaussianSource": (("frequency",), ("fwidth", "cutoff")),
            "Source": (("src",), ("component", "center", "amplitude")),
            "PML": (("thickness",), ("direction",)),
            "FluxRegion": ((), ("center", "direction")),
            "Simulation": ((), ("cell_size", "dimensions", "resolution", "Courant", "boundary_layers", "geometry", "sources", "eps_averaging")),
            "get_fluxes": (("monitor",), ()),
            "get_flux_freqs": (("monitor",), ()),
        }
        if name not in signatures:
            self.fail("Unsupported Meep call: " + name, node)
        values = self.signature(node, *signatures[name])
        p = plain(values)
        if name == "Vector3":
            self.require(all(v.kind == "number" or (v.kind == "enum" and v.data == "mp.inf") for v in values.values()), "Vector coordinates must be finite numbers or transverse mp.inf", node)
            return Value("vector", list(values.values()), locations(node, *values.values()))
        if name == "Medium":
            self.require(all(v.kind == "number" for v in values.values()), "Material value must be finite", node)
        elif name == "Block":
            self.require(values["size"].kind == values["center"].kind == "vector" and values["material"].kind == "Medium", "Block requires vectors and a scalar Medium", node)
        elif name == "GaussianSource":
            self.require(all(v.kind == "number" for v in values.values()), "Gaussian values must be finite", node)
        elif name == "Source":
            self.require(values["src"].kind == "GaussianSource" and values["center"].kind == "vector" and p["component"] == "mp.Ex" and values["amplitude"].kind == "number", "Only Gaussian Ex sources with finite amplitude are supported", node)
        elif name == "PML":
            self.require(values["thickness"].kind == "number" and p["direction"] == "mp.Z", "Only finite z-directed PML is supported", node)
        elif name == "FluxRegion":
            self.require(values["center"].kind == "vector" and p["direction"] == "mp.Z", "Only z-directed point flux regions are supported", node)
        elif name == "Simulation":
            self.require(len(self.sims) < 2, "Exactly two simulations are supported", node)
            if self.sims:
                self.require(self.sims[0].data["_state"] == "reset", "Reference must be reset before target construction", node)
            self.require(values["cell_size"].kind == "vector" and type(p["dimensions"]) is int and p["dimensions"] == 1 and type(p["resolution"]) is int and values["Courant"].kind == "number" and p["Courant"] == .5 and values["eps_averaging"].kind == "bool" and p["eps_averaging"] is True, "Simulation requires 1D, integer resolution, Courant=.5 and eps_averaging=True", node)
            for key, kind, count in (("boundary_layers", "PML", 1), ("sources", "Source", 1), ("geometry", "Block", None)):
                self.require(values[key].kind == "list" and all(x.kind == kind for x in values[key].data) and (count is None or len(values[key].data) == count), "Unsupported simulation " + key, node)
            values.update(_state="created", _id=len(self.sims), _monitors=[], _run=None, _subtraction=None, _reads=[])
            v = Value("simulation", values, locations(node))
            self.sims.append(v)
            return v
        elif name in {"get_fluxes", "get_flux_freqs"}:
            mon = values["monitor"]
            self.require(mon.kind == "monitor", "Readout must reference a tracked monitor", node)
            sim = self.sims[mon.data["_sim"]]
            self.require(sim.data["_state"] == "ran", "Flux readout must follow run and precede reset", node)
            sim.data["_reads"].append((name, mon.data["_id"], location(node)))
            return Value("readout", {"operation": name, "simulation": sim.data["_id"], "monitor": mon.data["_id"]}, locations(node, mon))
        return Value(name, values, locations(node, *values.values()))

    def sim_call(self, sim, name, node):
        d = sim.data
        if name == "add_flux":
            self.require(d["_state"] == "created" and len(d["_monitors"]) < 2, "Exactly two monitors must be added before each run", node)
            if len(node.args) == 2:
                v = self.signature(node, ('frequencies', 'region'), ('decimation_factor',))
                fs = v['frequencies']
                self.require(fs.kind == 'list' and 3 <= len(fs.data) <= 201 and all(x.kind == 'number' and x.data > 0 for x in fs.data), 'Explicit frequencies require 3..201 positive finite literals', node)
                grid = plain(fs)
                self.require(all(a < b for a,b in zip(grid, grid[1:])), 'Explicit frequencies must be strictly ascending', node)
                fcen = (grid[0] + grid[-1]) / 2
                df = grid[-1] - grid[0]
                v.update(fcen=Value('number',fcen,fs.locations), df=Value('number',df,fs.locations), nfreq=Value('number',len(grid),fs.locations))
            else:
                v = self.signature(node, ("fcen", "df", "nfreq", "region"), ("decimation_factor",))
            self.require(all(v[x].kind == "number" for x in ("fcen", "df", "nfreq", "decimation_factor")) and type(v["nfreq"].data) is int and v["region"].kind == "FluxRegion" and type(v["decimation_factor"].data) is int and v["decimation_factor"].data == 1, "Monitor requires finite spectral settings, integer nfreq and decimation_factor=1", node)
            v.update(_sim=d["_id"], _id=len(d["_monitors"]))
            result = Value("monitor", v, locations(node))
            d["_monitors"].append(result)
            return result
        if name == "run":
            v = self.signature(node, (), ("until_after_sources",))
            self.require(d["_state"] == "created" and len(d["_monitors"]) == 2 and v["until_after_sources"].kind == "number" and v["until_after_sources"].data >= 0, "Run requires two monitors and one nonnegative fixed post-source duration", node)
            d["_run"] = v["until_after_sources"]
            d["_state"] = "ran"
        elif name == "get_flux_data":
            v = self.signature(node, ("monitor",), ())
            mon = v["monitor"]
            self.require(d["_id"] == 0 and d["_state"] == "ran" and mon.kind == "monitor" and mon.data["_sim"] == 0, "Incident field data must come from a completed reference monitor", node)
            return Value("flux_data", {"_sim": 0, "_monitor": mon.data["_id"]}, locations(node, mon))
        elif name == "load_minus_flux_data":
            v = self.signature(node, ("monitor", "data"), ())
            mon, data = v["monitor"], v["data"]
            self.require(d["_id"] == 1 and d["_state"] == "created" and len(d["_monitors"]) == 2 and d["_subtraction"] is None and mon.kind == "monitor" and mon.data["_sim"] == 1 and data.kind == "flux_data", "One reference subtraction must precede the target run", node)
            d["_subtraction"] = (mon, data, location(node))
        elif name == "reset_meep":
            self.signature(node, (), ())
            self.require(d["_state"] == "ran", "Reset must follow a single completed run", node)
            d["_state"] = "reset"
        else:
            self.fail("Unsupported simulation method: " + name, node)
        return Value("none", None, locations(node))

    def extract(self):
        self.require(len(self.sims) == 2, "Exactly one empty reference and one film target are required", self.current_node)
        ref, target = self.sims
        r, t = plain(ref), plain(target)
        self.require(all(s.data["_state"] == "reset" for s in self.sims), "Both simulations must run once and reset", self.current_node)
        self.require(r["geometry"] == [] and 1 <= len(t["geometry"]) <= 8, "First simulation must be empty; target requires 1..8 layers", self.current_node)
        fields = {}; mapping = {}
        def put(key, value, *vals):
            fields[key] = value
            mapping[key] = unique_locations(loc for value in vals for loc in value.locations)
        layers = []
        for i, block in enumerate(t["geometry"]):
            size = block["size"]; material = block["material"]
            self.require(size[:2] == ["mp.inf", "mp.inf"] and type(size[2]) in (int, float), "Layers must be infinite transversely with finite z thickness", self.current_node)
            kind = next(iter(material)); layer = {"material_kind": kind, "material_value": material[kind], "thickness_um": size[2]}
            layers.append(layer)
            bv = target.data["geometry"].data[i]
            put(f"layers.{i}.material_kind", kind, bv.data["material"])
            put(f"layers.{i}.material_value", material[kind], bv.data["material"].data[kind])
            put(f"layers.{i}.thickness_um", size[2], bv.data["size"].data[2])
        thickness = sum(l["thickness_um"] for l in layers)
        cursor = -thickness / 2
        for block, layer in zip(t["geometry"], layers):
            self.require(same(block["center"], [0, 0, cursor + layer["thickness_um"] / 2]), "Target layers must be contiguous, ordered and centered at z=0", self.current_node)
            cursor += layer["thickness_um"]
        for key in ("cell_size", "dimensions", "resolution", "Courant", "boundary_layers", "eps_averaging"):
            self.require(same(r[key], t[key]), "Reference/target mismatch: " + key, self.current_node)
        cell = t["cell_size"]; pml = t["boundary_layers"][0]["thickness"]
        self.require(cell[:2] == [0, 0] and type(cell[2]) in (int, float), "Only a finite z cell is supported", self.current_node)
        air = (cell[2] - thickness - 2 * pml) / 2
        # Only repair a derived value one representable float outside a boundary.
        # Preserve every previously legal value exactly for archived provenance.
        for boundary, direction in ((3.0, -math.inf), (5.0, math.inf)):
            if air == math.nextafter(boundary, direction):
                self.numeric_normalizations.append({
                    "field": "numerics.air_um", "raw_value": air,
                    "normalized_value": boundary,
                    "reason": "derived-air-one-ulp-outside-supported-boundary",
                    "derivation": "(cell_z - total_layer_thickness - 2 * pml) / 2",
                })
                air = boundary
                break
        monitors = []
        for sim in self.sims:
            ms = sim.data["_monitors"]
            by_side = {}
            for mon in ms:
                pm = plain(mon)
                center = pm["region"]["center"]
                side = "reflection" if same(center, [0, 0, -thickness / 2 - 1.5]) else "transmission" if same(center, [0, 0, thickness / 2 + 1.5]) else None
                self.require(side is not None and side not in by_side, "Monitors must occupy the canonical reflection/transmission positions", self.current_node)
                by_side[side] = mon
            monitors.append(by_side)
        target_reflect = monitors[1]["reflection"]
        baseline_monitor = plain(target_reflect)
        fcen, df, nfreq = (baseline_monitor[k] for k in ("fcen", "df", "nfreq"))
        self.require(df > 0 and fcen - df / 2 > 0, "Spectrum requires positive frequencies and nonzero bandwidth", self.current_node)
        self.require(3 <= nfreq <= 201 and 0.5 <= 1 / (fcen + df / 2) < 1 / (fcen - df / 2) <= 5, "Spectrum exceeds the supported 3..201 samples / [0.5,5] wavelength-unit range", self.current_node)
        for sides in monitors:
            for mon in sides.values():
                self.require(all(same(plain(mon)[k], baseline_monitor[k]) for k in ("fcen", "df", "nfreq")), "All reference and target monitor frequency grids must match", self.current_node)
        explicit = baseline_monitor.get('frequencies')
        for sides in monitors:
            for mon in sides.values():
                self.require(same(plain(mon).get('frequencies'), explicit), 'Explicit reference/target monitor grids must match', self.current_node)
        for i, sim in enumerate(self.sims):
            needed = {monitors[i]["transmission"].data["_id"]}
            if i == 1: needed.add(monitors[i]["reflection"].data["_id"])
            seen = {mon for op, mon, _ in sim.data["_reads"] if op == "get_fluxes"}
            self.require(needed <= seen, "Missing required incident/target flux readout", self.current_node)
            src = plain(sim)["sources"][0]
            self.require(same(src["center"], [0, 0, -thickness / 2 - 2]) and same(src["src"], {"frequency": fcen, "fwidth": 2 * df, "cutoff": 5.0}), "Source center or Gaussian settings differ from the supported canonical recipe", self.current_node)
        sub = target.data["_subtraction"]
        if sub is not None:
            mon, data, loc = sub
            self.require(mon.data["_id"] == target_reflect.data["_id"] and data.data["_monitor"] == monitors[0]["reflection"].data["_id"], "Incident subtraction must pair the reference and target reflection monitors", self.current_node)
        after = number(target.data["_run"])
        self.require(after > 0, "Target post-source duration must be positive", self.current_node)
        numeric = {"resolution": t["resolution"], "after_sources": after, "pml_um": pml, "air_um": air, "source_amplitude": t["sources"][0]["amplitude"]}
        workflow = {"subtract_incident": sub is not None, "reference_amplitude": r["sources"][0]["amplitude"], "reference_time_factor": number(ref.data["_run"]) / after}
        put("numerics.resolution", numeric["resolution"], target.data["resolution"])
        put("numerics.after_sources", after, target.data["_run"])
        put("numerics.pml_um", pml, target.data["boundary_layers"].data[0].data["thickness"])
        put("numerics.air_um", air, target.data["cell_size"], target.data["geometry"], target.data["boundary_layers"])
        put("numerics.source_amplitude", numeric["source_amplitude"], target.data["sources"].data[0].data["amplitude"])
        put("workflow.reference_amplitude", workflow["reference_amplitude"], ref.data["sources"].data[0].data["amplitude"])
        put("workflow.reference_time_factor", workflow["reference_time_factor"], ref.data["_run"], target.data["_run"])
        fields["workflow.subtract_incident"] = sub is not None
        mapping["workflow.subtract_incident"] = [sub[2]] if sub else target.locations
        for k in ("fcen", "df", "nfreq"):
            put("spectrum." + k, baseline_monitor[k], target_reflect.data[k])
        # Record recognized settings which the canonical candidate cannot vary.
        # These are checked, not silently supplied from defaults.
        for prefix, sim, sides in zip(("reference", "target"), self.sims, monitors):
            for key in ("cell_size", "dimensions", "Courant", "eps_averaging"):
                put(prefix + "." + key, plain(sim.data[key]), sim.data[key])
            source = sim.data["sources"].data[0]
            for key in ("component", "center"):
                put(prefix + ".source." + key, plain(source.data[key]), source.data[key])
            for key in ("frequency", "fwidth", "cutoff"):
                value = source.data["src"].data[key]
                put(prefix + ".source." + key, plain(value), value)
            for side, monitor in sides.items():
                region = monitor.data["region"]
                for key in ("center", "direction"):
                    put(prefix + "." + side + "." + key, plain(region.data[key]), region.data[key])
                put(prefix + "." + side + ".decimation_factor", 1, monitor.data["decimation_factor"])
        for i, block in enumerate(target.data["geometry"].data):
            put(f"geometry.{i}.center", plain(block.data["center"]), block.data["center"])
        candidate = {"schema_version": 1, "adapter": "film1d-v1", "layers": layers, "numerics": numeric, "workflow": workflow}
        problem = candidate_problem(candidate)
        if problem: self.fail(problem["reason"], field="candidate")
        spectrum = {"fcen": fcen, "df": df, "nfreq": nfreq}
        if explicit is not None:
            spectrum['frequencies'] = explicit
            put('spectrum.frequencies', explicit, target_reflect.data['frequencies'])
        return candidate, spectrum, fields, mapping


def preview_bytes(raw, source_name="input.py"):
    """Return a reviewable result; no source dependencies are imported or executed."""
    if not isinstance(raw, bytes):
        raise TypeError("Script input must be bytes")
    sha = hashlib.sha256(raw).hexdigest()
    result = {"schema_version": 1, "importer": IMPORTER, "status": "UNSUPPORTED", "claim": CLAIM,
              "source": {"name": str(source_name), "sha256": sha, "byte_count": len(raw)},
              "candidate": None, "extracted_fields": {}, "source_locations": {}, "unresolved": [],
              "task_confirmation": {"required": True, "status": "NOT_PROVIDED", "note": "Review and separately confirm task physics, material intent, wavelengths, nfreq, and one micrometre per Meep unit. No task is inferred from comments or the candidate."}}
    reader = None
    try:
        if len(raw) > MAX_BYTES:
            raise Unsupported("Script exceeds 128 KiB parser limit")
        encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
        if encoding not in {"utf-8", "utf-8-sig", "utf8"}:
            raise Unsupported("Only UTF-8 coding declarations are supported; declared encoding: " + encoding)
        source = raw.decode("utf-8-sig")
        tree = ast.parse(source, filename="<untrusted-meep-input>")
        stack = [(tree, 0)]; count = 0
        while stack:
            node, depth = stack.pop(); count += 1
            if count > MAX_NODES or depth > MAX_DEPTH:
                raise Unsupported("Script exceeds bounded AST node/depth limits", node if hasattr(node, "lineno") else None)
            stack.extend((child, depth + 1) for child in ast.iter_child_nodes(node))
        reader = Reader(source)
        reader.read(tree)
        candidate, spectrum, fields, mapping = reader.extract()
        provenance = {"schema_version": 1, "importer": IMPORTER, "source_name": str(source_name),
                      "source_sha256": sha, "source_bytes_base64": base64.b64encode(raw).decode("ascii"),
                      "source_locations": mapping, "spectrum": spectrum, "extracted_recipe_sha256": digest(candidate), "claim": CLAIM}
        if reader.numeric_normalizations:
            provenance["numeric_normalizations"] = reader.numeric_normalizations
        candidate["origin"] = {"kind": "meep-ast-canonical-import", "patch_round": 0, "script_import": provenance}
        result.update(status="EXTRACTED", candidate=candidate, extracted_fields=fields, source_locations=mapping, spectrum=spectrum)
    except (Unsupported, SyntaxError, UnicodeError, RecursionError, MemoryError) as exc:
        node = getattr(exc, "node", None) or (reader.current_node if reader else None)
        result["unresolved"].append({"field": getattr(exc, "field", None) or (reader.current_field if reader else "script"),
                                     "reason": str(exc), "location": location(node),
                                     "expression": ast.get_source_segment(reader.source, node) if reader and node is not None else None})
        # Retain safe, resolved literal bindings without filling unknown recipe fields.
        if reader:
            result["resolved_numeric_bindings"] = {k: {"value": v.data, "source_locations": v.locations} for k, v in reader.bindings.items() if v.kind == "number"}
        result["partial_candidate"] = {"layers": None, "numerics": None, "workflow": None}
    if reader and reader.numeric_normalizations:
        result["numeric_normalizations"] = reader.numeric_normalizations
    return result


def read_source(path):
    # Take one bounded byte snapshot. Never import the file or follow paths inside it.
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Script exceeds 128 KiB limit; no truncated-source provenance is produced")
    return raw


def preview_script(path):
    return preview_bytes(read_source(path), Path(path).name)


def decode_source(info):
    if not isinstance(info, dict):
        raise ValueError("Missing script import provenance")
    encoded = info.get("source_bytes_base64")
    if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_BYTES + 2) // 3):
        raise ValueError("Invalid or oversized original-script bytes")
    try: raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc: raise ValueError("Invalid original-script encoding") from exc
    if len(raw) > MAX_BYTES or hashlib.sha256(raw).hexdigest() != info.get("source_sha256"):
        raise ValueError("Original-script byte hash mismatch")
    return raw


def validate_provenance(candidate, task):
    """Reparse embedded original bytes and replay any approved bounded patch chain."""
    info = candidate.get("origin", {}).get("script_import")
    raw = decode_source(info)
    preview = preview_bytes(raw, info.get("source_name", "input.py"))
    if preview["status"] != "EXTRACTED":
        raise ValueError("Original script is outside the recognized import scope")
    original = preview["candidate"]
    if original["origin"]["script_import"] != info:
        raise ValueError("Script provenance differs from a fresh parse of original bytes")
    chain = candidate.get("origin", {}).get("script_patch_history", [])
    if not isinstance(chain, list) or len(chain) > 2:
        raise ValueError("Invalid script patch history")
    if chain:
        from .agent import apply_patch
        for patch in chain:
            if not isinstance(patch, dict):
                raise ValueError("Each script patch history entry must be an object")
            changes = patch.get("changes")
            if not isinstance(changes, list) or len(changes) != 1 or not isinstance(changes[0], dict) or not isinstance(changes[0].get("path"), list):
                raise ValueError("Malformed bounded change in script patch history")
            try:
                original = apply_patch(task, original, patch)
            except (AttributeError, KeyError, TypeError, IndexError) as exc:
                raise ValueError("Malformed script patch history") from exc
            if patch.get("diagnostic_provenance"):
                original["origin"]["diagnostic_provenance"] = patch["diagnostic_provenance"]
    if candidate != original:
        raise ValueError("Candidate differs from the extracted recipe or approved bounded patch history")
    problem = task_problem(task)
    if problem:
        raise ValueError("Separately confirmed supported task required: " + problem["reason"])
    spec = preview["spectrum"]
    lo, hi = 1 / task["wavelength_um"][1], 1 / task["wavelength_um"][0]
    if not same([spec["fcen"], spec["df"], spec["nfreq"]], [(lo + hi) / 2, hi - lo, task["nfreq"]]):
        raise ValueError("Imported monitor spectrum differs from the locked task; refusing to replace it with task settings")
    from .sampling import frequencies
    grid = spec.get('frequencies')
    if grid is None:
        if 'sampling' in task:
            raise ValueError('Equal-wavelength task requires explicit matching DFT frequencies in the imported script; equal-frequency monitors cannot be silently replaced')
    elif not same(grid, frequencies(task)):
        raise ValueError('Explicit imported monitor frequencies differ from locked task sampling')
    return raw, preview


def write_preview(script_path, output_dir):
    """Create a new inspection bundle, never overwriting prior source/evidence."""
    from .core import write_json
    raw = read_source(script_path)
    preview = preview_bytes(raw, Path(script_path).name)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=False)
    (out / "script.original.py").write_bytes(raw)
    write_json(out / "import-report.json", preview)
    if preview["candidate"] is not None:
        write_json(out / "candidate.json", preview["candidate"])
    return preview, out
