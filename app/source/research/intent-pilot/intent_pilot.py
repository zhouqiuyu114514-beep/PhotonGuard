"""Bounded, synthetic-only intent review proof. Python standard library only.

No natural-language extraction, approval, task export, network, or solver.
SPDX-License-Identifier: GPL-2.0-or-later
"""
from __future__ import annotations

import argparse
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import re


PHYSICS = {
    "dimensions": ("count", 1), "angle_deg": ("deg", 0),
    "lossless": ("bool", True), "dispersive": ("bool", False),
    "isotropic": ("bool", True), "mu": ("1", 1),
    "n_incident": ("1", 1), "n_exit": ("1", 1),
}
UNITS = {"physics." + k: v[0] for k, v in PHYSICS.items()}
UNITS.update({"units_um": "um", "layers.0.n": "1",
              "layers.0.thickness_um": "um", "wavelength_um.0": "um",
              "wavelength_um.1": "um", "nfreq": "count"})
PATHS = tuple(UNITS)
LENGTH_FACTORS = {"nm": Decimal("0.001"), "um": Decimal(1),
                  "mm": Decimal(1000)}
LIMIT_BYTES = 262144


def require(condition, message):
    if not condition:
        raise ValueError(message)


def exact(value, keys, context):
    require(type(value) is dict and set(value) == set(keys),
            context + ": exact keys required")


def sequence(value, maximum, context):
    require(type(value) is list and len(value) <= maximum,
            context + ": bounded array required")


def identifier(value):
    require(type(value) is str and re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", value),
            "invalid identifier")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def reject_constant(value):
    raise ValueError("non-finite JSON number")


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def finite_float(text):
    value = float(text)
    require(math.isfinite(value), "non-finite JSON number")
    return value


def loads(raw):
    require(len(raw) <= LIMIT_BYTES, "input too large")
    return json.loads(raw, object_pairs_hook=unique_keys,
                      parse_constant=reject_constant, parse_float=finite_float)


def read_json(path):
    with Path(path).open("rb") as stream:
        return loads(stream.read(LIMIT_BYTES + 1))


def normalized(fact):
    """Only explicit typed quantities; decimal arithmetic, no inference."""
    path, value, unit = fact["path"], fact["value"], fact["unit"]
    target = UNITS[path]
    allowed = set(LENGTH_FACTORS) if target == "um" else {target}
    require(unit is None or (type(unit) is str and unit in allowed),
            "unsupported or dimensionally wrong unit: " + path)
    if value is not None:
        if target == "bool":
            require(type(value) is bool, "boolean required: " + path)
        else:
            require(type(value) in (int, float), "number required: " + path)
            number = Decimal(str(value))
            require(number.is_finite() and abs(number) <= Decimal("1e12"),
                    "finite bounded number required: " + path)
            if target == "count":
                require(type(value) is int, "integer required: " + path)
    if value is None or unit is None:
        return None
    if target == "bool":
        return value
    number = Decimal(str(value))
    return number * LENGTH_FACTORS[unit] if target == "um" else number


def supported(path, value):
    # Narrow pilot scope, not a substitute for the frozen physical verifier.
    if path.startswith("physics."):
        return value == PHYSICS[path.split(".")[1]][1]
    if path == "units_um":
        return value == 1
    if path == "layers.0.n":
        return Decimal(1) <= value <= Decimal(5)
    if path == "layers.0.thickness_um":
        return Decimal("0.02") <= value <= Decimal(5)
    if path.startswith("wavelength_um."):
        return Decimal("0.5") <= value <= Decimal(5)
    return 3 <= value <= 201


def validate_bundle(bundle):
    exact(bundle, {"schema_version", "kind", "documents", "facts"}, "bundle")
    require(type(bundle["schema_version"]) is int and bundle["schema_version"] == 1,
            "unsupported bundle schema")
    require(bundle["kind"] == "synthetic_development", "synthetic fixtures only")
    sequence(bundle["documents"], 16, "documents")
    sequence(bundle["facts"], 128, "facts")
    documents = {}
    for doc in bundle["documents"]:
        exact(doc, {"id", "kind", "lines"}, "document")
        identifier(doc["id"])
        require(doc["id"] not in documents, "duplicate document ID")
        require(doc["kind"] in ("independent_spec", "ast_observation"),
                "invalid document kind")
        sequence(doc["lines"], 128, "document lines")
        require(all(type(line) is str and 0 < len(line) <= 2000
                    and "\n" not in line and "\r" not in line for line in doc["lines"]),
                "invalid source lines")
        documents[doc["id"]] = doc
    facts = {}
    for fact in bundle["facts"]:
        exact(fact, {"id", "path", "value", "unit", "source"}, "fact")
        identifier(fact["id"])
        require(fact["id"] not in facts, "duplicate fact ID")
        require(type(fact["path"]) is str and fact["path"] in UNITS,
                "illegal field path")
        source = fact["source"]
        exact(source, {"document_id", "line", "quote"}, "source")
        identifier(source["document_id"])
        require(source["document_id"] in documents, "unknown source document")
        doc = documents[source["document_id"]]
        line = source["line"]
        require(type(line) is int and 1 <= line <= len(doc["lines"]),
                "invalid source line")
        require(type(source["quote"]) is str and source["quote"] == doc["lines"][line - 1],
                "source quote mismatch")
        normalized(fact)
        facts[fact["id"]] = fact
    return documents, facts


def public_value(value):
    # Decimal strings avoid silently re-rounding physical quantities in JSON.
    if isinstance(value, Decimal):
        return format(value, "f")
    return value


def review(bundle, proposal):
    """Pure review function; values come only from independently supplied facts.

    A quote/line match verifies the reference, not the truth or meaning of the
    hand-annotated fact. All results require human semantic review.
    """
    documents, facts = validate_bundle(bundle)
    exact(proposal, {"schema_version", "kind", "bundle_sha256", "fields"}, "proposal")
    require(type(proposal["schema_version"]) is int and proposal["schema_version"] == 1,
            "unsupported proposal schema")
    require(proposal["kind"] == "handwritten_mock", "handwritten mock label required")
    require(proposal["bundle_sha256"] == digest(bundle), "stale or different bundle")
    sequence(proposal["fields"], len(PATHS), "proposal fields")
    require(len(proposal["fields"]) == len(PATHS), "all pilot paths required")
    decisions = {}
    for field in proposal["fields"]:
        exact(field, {"path", "state", "evidence_ids"}, "proposal field")
        path = field["path"]
        require(type(path) is str and path in UNITS, "illegal proposal path")
        require(path not in decisions, "duplicate proposal path")
        require(field["state"] in ("proposed", "unknown", "conflict", "unsupported"),
                "invalid state; approval is unavailable")
        sequence(field["evidence_ids"], 128, "evidence IDs")
        for item in field["evidence_ids"]:
            identifier(item)
        require(len(set(field["evidence_ids"])) == len(field["evidence_ids"]),
                "duplicate evidence ID")
        eligible = [fact for fact in facts.values() if fact["path"] == path
                    and documents[fact["source"]["document_id"]]["kind"] == "independent_spec"]
        require(set(field["evidence_ids"]) == {fact["id"] for fact in eligible},
                "cite all independent facts for this path; no script fallback")
        values = [normalized(fact) for fact in eligible]
        known = {value for value in values if value is not None}
        if len(known) > 1:
            state, value = "conflict", None
        elif not values or None in values:
            state, value = "unknown", None
        else:
            value = next(iter(known))
            state = "proposed" if supported(path, value) else "unsupported"
        require(field["state"] == state, "state inconsistent with sources: " + path)
        decisions[path] = {"path": path, "state": state,
                           "suggested_value": public_value(value) if state == "proposed" else None,
                           "unit": UNITS[path], "evidence_ids": sorted(field["evidence_ids"]),
                           "evidence": [{"id": fact["id"], "value": fact["value"],
                                         "unit": fact["unit"], "source": fact["source"]}
                                        for fact in eligible]}
    questions = []
    for path in PATHS:
        state = decisions[path]["state"]
        if state == "unknown":
            questions.append({"paths": [path], "reason": state,
                              "text": f"请依据独立规格补充 {path} 的明确值和单位（目标 {UNITS[path]}）；当前留空。"})
        elif state == "conflict":
            questions.append({"paths": [path], "reason": state,
                              "text": f"{path} 的独立来源不一致，请明确采用哪项并记录依据；当前留空。"})
    lower, upper = (decisions["wavelength_um." + str(i)] for i in (0, 1))
    if all(item["state"] == "proposed" for item in (lower, upper)):
        if Decimal(lower["suggested_value"]) >= Decimal(upper["suggested_value"]):
            for item in (lower, upper):
                item["state"], item["suggested_value"] = "conflict", None
            questions.append({"paths": [lower["path"], upper["path"]], "reason": "invalid_order",
                              "text": "请确认递增的波长端点；当前两个端点留空。"})
    blockers = [path for path in PATHS if decisions[path]["state"] == "unsupported"]
    status = "OUT_OF_SCOPE" if blockers else "CLARIFICATION_REQUIRED" if questions else "REVIEW_REQUIRED"
    return {"schema_version": 1, "kind": "synthetic_offline_review",
            "bundle_sha256": digest(bundle), "proposal_sha256": digest(proposal),
            "status": status, "task_approved": False, "task_lock_created": False,
            "model_calls": 0, "solver_calls": 0,
            "source_semantics_verified": False, "human_review_required": True,
            "note": "结构化事实由开发样例作者手写；引用匹配不证明文本语义。数值字符串为精确十进制；本结果不是 task.json。",
            "fields": [decisions[path] for path in PATHS], "questions": questions,
            "scope_blockers": blockers,
            "ignored_script_fact_ids": [fact["id"] for fact in facts.values()
                                        if documents[fact["source"]["document_id"]]["kind"] == "ast_observation"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle")
    parser.add_argument("proposal")
    args = parser.parse_args()
    try:
        result = review(read_json(args.bundle), read_json(args.proposal))
    except (ValueError, OSError, UnicodeError) as exc:
        parser.exit(2, "REJECTED: " + str(exc) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
