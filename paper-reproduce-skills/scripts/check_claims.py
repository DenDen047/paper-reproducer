#!/usr/bin/env python3
"""check_claims.py — deterministic paper-claim comparator (P0-C).

Claim verification is split into two roles so that no single agent both
produces and grades the numbers:

  * extraction (LLM, zero-context subagent): reads reports/eval/ and writes
    reports/_observed.json with the observed value + evidence provenance
    (file path + literal snippet). The extractor is given metric names only,
    never paper_target, so it cannot nudge values toward the claim.
  * judgment (this script, code): parses tolerance strings, validates the
    evidence provenance, and assigns the claims_verification status enum.

Anti-fabrication checks per observed entry:
  1. evidence_path exists and is readable as text
  2. evidence_snippet literally appears in that file (whitespace-normalized)
  3. the observed number appears in the snippet

Any failed check demotes the claim to not_evaluated with the reason recorded
in the audit block — a fabricated number can never surface as matched.

Verdict semantics (docs/reimplement-improvements.md left matched vs
within_tolerance ambiguous; this is the canonical definition):
  higher_better:  observed >= target                    -> matched
                  target - tol <= observed < target     -> within_tolerance
                  observed < target - tol               -> missed
  lower_better:   mirrored
  unknown:        |observed - target| <= tol            -> within_tolerance
                  else                                  -> missed
  (unknown direction never yields matched: without knowing which way is
   better, a deviation cannot be called an improvement)

Exit code 0 even when claims are missed or not evaluated (NEVER STOP);
2 only on genuine usage errors (unreadable analysis.json, bad flags).
--output is always written, so the downstream jq merge never sees a
missing file. stdlib only.
"""
import argparse
import json
import os
import re
import sys

NUM_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")

# metric-name keywords for direction inference. Checked as lowercase
# substrings except the short/ambiguous ones, which require word boundaries.
_HIGHER = ["psnr", "ssim", "accuracy", "precision", "recall", "miou",
           "success rate", "pck", "dice", "auc", "top-1", "top1", "f1", "map"]
_LOWER = ["chamfer", "rmse", "mse", "mae", "lpips", "fid", "kid", "error",
          "epe", "ate", "rpe", "loss", "distance", "dist"]
_HIGHER_WB = ["acc", "ap", "iou"]
_LOWER_WB = ["cd", "l1", "l2"]


def infer_direction(claim):
    explicit = claim.get("direction")
    if explicit in ("higher_better", "lower_better"):
        return explicit
    name = str(claim.get("metric_name", "")).lower()
    if "↑" in name:  # ↑
        return "higher_better"
    if "↓" in name:  # ↓
        return "lower_better"
    for kw in _HIGHER:
        if kw in name:
            return "higher_better"
    for kw in _LOWER:
        if kw in name:
            return "lower_better"
    for kw in _HIGHER_WB:
        if re.search(r"\b{}\b".format(re.escape(kw)), name):
            return "higher_better"
    for kw in _LOWER_WB:
        if re.search(r"\b{}\b".format(re.escape(kw)), name):
            return "lower_better"
    return "unknown"


def parse_tolerance(tol_str, target):
    """Parse 'rel±10%' / 'abs±0.3' (also rel+-10% etc.) into an absolute width.

    Returns (abs_width, warning_or_None).
    """
    s = str(tol_str or "").strip().lower().replace("±", "+-")
    m = re.match(r"^(rel|abs)\s*\+-\s*([0-9.]+)\s*(%?)\s*(pt)?$", s)
    if not m:
        return abs(target) * 0.10, "unparseable tolerance {!r}; fell back to rel±10%".format(tol_str)
    kind, raw, pct, _pt = m.groups()
    try:
        val = float(raw)
    except ValueError:
        return abs(target) * 0.10, "unparseable tolerance {!r}; fell back to rel±10%".format(tol_str)
    if kind == "rel":
        # rel is a percentage of the target whether or not '%' was written
        return abs(target) * val / 100.0, None
    # abs: '%' / 'pt' suffixes are just units of the metric itself
    return val, None


def _norm_ws(s):
    return re.sub(r"\s+", " ", s).strip()


def check_evidence(entry, repo_root):
    """Return None if evidence holds, else a reason string."""
    path = entry.get("evidence_path")
    snippet = entry.get("evidence_snippet")
    observed = entry.get("observed")
    if not path or not isinstance(path, str):
        return "evidence_path missing"
    if not isinstance(snippet, str) or not snippet.strip():
        return "evidence_snippet missing"
    if not isinstance(observed, (int, float)) or isinstance(observed, bool):
        return "observed is not a number"
    full = path if os.path.isabs(path) else os.path.join(repo_root, path)
    if not os.path.isfile(full):
        return "evidence file not found: {}".format(path)
    try:
        with open(full, encoding="utf-8", errors="strict") as f:
            content = f.read()
    except (UnicodeDecodeError, OSError) as e:
        return "evidence file not readable as text ({}): {}".format(
            type(e).__name__, path)
    if _norm_ws(snippet) not in _norm_ws(content):
        return "evidence_snippet not found in {}".format(path)
    for tok in NUM_RE.findall(snippet):
        try:
            v = float(tok)
        except ValueError:
            continue
        if abs(v - float(observed)) <= max(1e-9, abs(float(observed)) * 1e-9):
            return None
    return "observed value {} does not appear in evidence_snippet".format(observed)


def judge(claim, observed, tol_abs):
    target = float(claim["paper_target"])
    direction = infer_direction(claim)
    if direction == "higher_better":
        if observed >= target:
            return "matched"
        if observed >= target - tol_abs:
            return "within_tolerance"
        return "missed"
    if direction == "lower_better":
        if observed <= target:
            return "matched"
        if observed <= target + tol_abs:
            return "within_tolerance"
        return "missed"
    if abs(observed - target) <= tol_abs:
        return "within_tolerance"
    return "missed"


def build_results(analysis, observed_doc, repo_root):
    claims = analysis.get("paper_claims") or []
    observed_entries = {}
    duplicate_ids = []
    for entry in (observed_doc or {}).get("results", []):
        cid = entry.get("id")
        if cid in observed_entries:
            duplicate_ids.append(cid)
        observed_entries[cid] = entry

    results, failures = [], []
    for claim in claims:
        cid = claim.get("id")
        target = float(claim["paper_target"])
        tol_abs, tol_warn = parse_tolerance(claim.get("tolerance"), target)
        if tol_warn:
            failures.append({"id": cid, "reason": tol_warn})
        row = {
            "id": cid,
            "metric_name": claim.get("metric_name"),
            "paper_target": target,
            "tolerance": claim.get("tolerance"),
            "observed": None,
            "delta_rel_pct": None,
            "status": "not_evaluated",
            "claim_source": claim.get("claim_source", ""),
            "evidence_path": None,
            "note": None,
        }
        entry = observed_entries.get(cid)
        if entry is None:
            row["note"] = "no observed entry for this claim id"
            results.append(row)
            continue
        reason = check_evidence(entry, repo_root)
        if reason is not None:
            row["note"] = "evidence check failed: {}".format(reason)
            failures.append({"id": cid, "reason": reason})
            results.append(row)
            continue
        observed = float(entry["observed"])
        row["observed"] = observed
        row["evidence_path"] = entry["evidence_path"]
        if target != 0:
            row["delta_rel_pct"] = round((observed - target) / abs(target) * 100, 2)
        row["status"] = judge(claim, observed, tol_abs)
        if infer_direction(claim) == "unknown":
            row["note"] = "metric direction unknown; matched is unreachable, judged as two-sided band"
        results.append(row)

    for cid in duplicate_ids:
        failures.append({"id": cid, "reason": "duplicate id in _observed.json; last entry used"})
    return results, failures


def main(argv=None):
    p = argparse.ArgumentParser(description="Deterministic paper-claim comparator (P0-C).")
    p.add_argument("--analysis", default="reports/analysis.json")
    p.add_argument("--observed", default="reports/_observed.json")
    p.add_argument("--output", default="reports/_claims.json")
    p.add_argument("--repo-root", default=".",
                   help="Base dir for relative evidence_path resolution.")
    args = p.parse_args(argv)

    try:
        with open(args.analysis, encoding="utf-8") as f:
            analysis = json.load(f)
    except (OSError, ValueError) as e:
        print("check_claims: cannot read {}: {}".format(args.analysis, e), file=sys.stderr)
        return 2

    observed_doc = None
    observed_note = None
    try:
        with open(args.observed, encoding="utf-8") as f:
            observed_doc = json.load(f)
    except FileNotFoundError:
        observed_note = "{} not found; all claims not_evaluated".format(args.observed)
    except (OSError, ValueError) as e:
        observed_note = "{} unreadable ({}); all claims not_evaluated".format(args.observed, e)

    results, failures = build_results(analysis, observed_doc, args.repo_root)
    if observed_note:
        failures.append({"id": None, "reason": observed_note})

    counts = {s: 0 for s in ("matched", "within_tolerance", "missed", "not_evaluated")}
    for r in results:
        counts[r["status"]] += 1
    out = {
        "generated_by": "check_claims.py",
        "results": results,
        "audit": {"total": len(results), **counts, "evidence_failures": failures},
    }
    out_dir = os.path.dirname(os.path.abspath(args.output))
    os.makedirs(out_dir, exist_ok=True)
    tmp = args.output + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    os.replace(tmp, args.output)

    summary = "check_claims: {total} claims — {matched} matched, {within_tolerance} within_tolerance, {missed} missed, {not_evaluated} not_evaluated".format(
        total=len(results), **counts)
    print(summary)
    for fail in failures:
        print("check_claims: WARN [{}] {}".format(fail["id"], fail["reason"]), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
