#!/usr/bin/env python3
"""provision_manual_assets.py — inventory & placement helper for the
manual-asset registry (license-gated models such as SMPL / SMPL-X / SMAL).

paper-reproducer NEVER downloads, bundles, mirrors, or redistributes these
assets. This script only:
  (a) `inventory` — reports which manually-provisioned assets are present in
      the host registry, with a user-friendly first-run guide when missing;
  (b) `place`     — copies a user-provided file from the mounted registry into
      a target repo path and records it in .gitignore so it never enters git
      or the success archive.

stdlib only (runs on the host during bootstrap.sh AND inside the container).
Never exits non-zero on a missing asset — graceful degradation is the contract
(see skills/reimplement Phase 3 "NEVER STOP"). Non-zero exit is reserved for
genuine usage errors (bad manifest, missing args).
"""
import argparse
import fnmatch
import json
import os
import shutil
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MANIFEST = os.path.normpath(os.path.join(_HERE, "..", "registry", "manifest.json"))
GITIGNORE_MARKER = "# manual-assets (third-party licensed; never commit — provision_manual_assets.py)"


def _expand(p):
    return os.path.abspath(os.path.expanduser(p))


def _load_manifest(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _registry_files(root):
    """All file paths under root, relative to root (empty if root absent)."""
    out = []
    if not os.path.isdir(root):
        return out
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            out.append(os.path.relpath(os.path.join(dirpath, fn), root))
    return out


def _asset_found(asset, root, all_files):
    """Return the list of registry-relative paths satisfying this asset."""
    found = []
    for rel in asset.get("canonical_files", []):
        if os.path.isfile(os.path.join(root, rel)):
            found.append(rel)
    if not found:
        for glob in asset.get("filename_globs", []):
            found.extend(f for f in all_files if fnmatch.fnmatch(os.path.basename(f), glob))
    # de-dup, stable order
    seen, uniq = set(), []
    for f in found:
        if f not in seen:
            seen.add(f)
            uniq.append(f)
    return uniq


# --- inventory -------------------------------------------------------------

_T = {
    "ja": {
        "header": "── 手動資産の初回セットアップのご案内 ──────────────────",
        "footer": "──────────────────────────────────────────────",
        "intro": [
            "SMPL / SMPL-X / MANO / SMAL など一部の CV 論文は、ライセンス登録が",
            "必須で自動ダウンロードできないモデルに依存します。",
            "「一度だけ」手作業で用意すれば、以後の再現は自動で進みます。",
        ],
        "registry": "レジストリ: {root}  ({state})",
        "state_absent": "未作成",
        "state_partial": "{n}/{total} 配置済み",
        "instruct": "  必要なモデルを各サイトで登録・DL し、次のパスに配置してください:",
        "detail": "詳細・ライセンス・全ファイル一覧: paper-reproduce-skills/registry/ASSETS.md",
        "note1": "※ これは一般的なヒントです。今回の repo が実際に必要とする資産は",
        "note1b": "  解析後に /reimplement が具体的に指示します。",
        "note2": "※ 未配置でも処理は続行します（レポートに取得手順を記載）。",
        "complete": "manual assets: {n}/{total} present ({root})",
    },
    "en": {
        "header": "── Manual-asset first-time setup ──────────────────────",
        "footer": "──────────────────────────────────────────────",
        "intro": [
            "Some CV papers depend on license-gated models (SMPL / SMPL-X / MANO /",
            "SMAL, ...) that cannot be downloaded automatically.",
            "Provision them once by hand and every later run resolves them for you.",
        ],
        "registry": "registry: {root}  ({state})",
        "state_absent": "not created",
        "state_partial": "{n}/{total} present",
        "instruct": "  Register & download each model, then place it at:",
        "detail": "Details, licenses, full file list: paper-reproduce-skills/registry/ASSETS.md",
        "note1": "* This is a general hint. The assets THIS repo actually needs",
        "note1b": "  will be named precisely by /reimplement after analysis.",
        "note2": "* Missing assets do not stop the run (remediation goes into the report).",
        "complete": "manual assets: {n}/{total} present ({root})",
    },
}


def cmd_inventory(args):
    lang = args.lang if args.lang in _T else "ja"
    t = _T[lang]
    manifest = _load_manifest(args.manifest)
    root = _expand(args.root)
    assets = manifest.get("assets", [])
    all_files = _registry_files(root)
    rows = []  # (asset, found_list)
    for a in assets:
        rows.append((a, _asset_found(a, root, all_files)))
    n_present = sum(1 for _a, f in rows if f)
    total = len(rows)
    complete = n_present == total and os.path.isdir(root)

    # Quiet path: fully provisioned and not explicitly listing.
    if complete and not args.list:
        print(t["complete"].format(n=n_present, total=total, root=root))
        return 0

    out = [t["header"]]
    out += t["intro"]
    out.append("")
    if not os.path.isdir(root):
        state = t["state_absent"]
    else:
        state = t["state_partial"].format(n=n_present, total=total)
    out.append(t["registry"].format(root=root, state=state))
    out.append(t["instruct"])
    for a, found in rows:
        mark = "✓" if found else "✗"
        canon = (a.get("canonical_files") or [a["key"] + "/"])[0]
        out.append("    [{m}] {name:<8} {root}/{path}".format(
            m=mark, name=a.get("display_name", a["key"]), root=root, path=canon))
        if not found:
            out.append("             {url}".format(url=a.get("source_url", "")))
    out.append("")
    out.append(t["detail"])
    out.append("")
    out.append(t["note1"])
    out.append(t["note1b"])
    out.append(t["note2"])
    out.append(t["footer"])
    print("\n".join(out))
    return 0


# --- place -----------------------------------------------------------------

def _add_to_gitignore(dest_rel):
    gi = ".gitignore"
    existing = []
    if os.path.isfile(gi):
        with open(gi, encoding="utf-8") as f:
            existing = f.read().splitlines()
    if dest_rel in existing:
        return
    with open(gi, "a", encoding="utf-8") as f:
        prefix = ""
        if existing and existing[-1].strip() != "":
            prefix = "\n"
        if GITIGNORE_MARKER not in existing:
            f.write(prefix + GITIGNORE_MARKER + "\n")
            prefix = ""
        f.write(prefix + dest_rel + "\n")


def _is_under(path, base):
    """True if realpath(path) is inside realpath(base)."""
    real = os.path.realpath(path)
    base_real = os.path.realpath(base)
    return real == base_real or real.startswith(base_real + os.sep)


def cmd_place(args):
    root = _expand(args.root)
    src = os.path.join(root, args.src)
    dest = args.dest
    result = {"asset": args.asset, "src": args.src, "dest": dest}
    cwd = os.path.abspath(os.getcwd())
    abs_dest = os.path.abspath(dest)

    # --src is registry-relative and --dest repo-relative by contract; reject
    # anything that escapes those roots (absolute paths, ../, symlink tricks).
    if os.path.isabs(args.src) or not _is_under(src, root):
        result["status"] = "invalid_path"
        result["reason"] = "src escapes registry root {}".format(root)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if not _is_under(abs_dest, cwd):
        result["status"] = "invalid_path"
        result["reason"] = "dest escapes repo root {}".format(cwd)
        print(json.dumps(result, ensure_ascii=False))
        return 0

    if not os.path.isfile(src):
        result["status"] = "missing_in_registry"
        result["registry_root"] = root
        if args.source_url:
            result["source_url"] = args.source_url
        print(json.dumps(result, ensure_ascii=False))
        return 0

    dest_dir = os.path.dirname(abs_dest)
    if dest_dir:
        os.makedirs(dest_dir, exist_ok=True)
    # Copy via tmp + rename so an interrupted copy never leaves a truncated
    # file at dest, then verify the byte count actually matches the source.
    src_size = os.path.getsize(src)
    tmp = abs_dest + ".tmp-provision"
    shutil.copy2(src, tmp)
    if os.path.getsize(tmp) != src_size:
        os.remove(tmp)
        result["status"] = "copy_size_mismatch"
        result["expected_bytes"] = src_size
        print(json.dumps(result, ensure_ascii=False))
        return 0
    os.replace(tmp, abs_dest)
    if src_size == 0:
        result["status"] = "placed_empty"
        result["bytes"] = 0
        print(json.dumps(result, ensure_ascii=False))
        return 0

    _add_to_gitignore(os.path.relpath(abs_dest, cwd))
    result["gitignored"] = True
    result["status"] = "placed"
    result["bytes"] = src_size
    print(json.dumps(result, ensure_ascii=False))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Manual-asset registry inventory & placement helper.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("inventory", help="Report present/missing manual assets.")
    pi.add_argument("--root", default=os.environ.get("MANUAL_ASSETS_DIR", "manual-assets"))
    pi.add_argument("--manifest", default=DEFAULT_MANIFEST)
    pi.add_argument("--lang", default="ja")
    pi.add_argument("--list", action="store_true", help="Force full listing even when complete.")
    pi.set_defaults(func=cmd_inventory)

    pp = sub.add_parser("place", help="Copy one registry file into a repo path + gitignore it.")
    pp.add_argument("--root", default="/manual-assets")
    pp.add_argument("--src", required=True, help="Registry-relative source path, e.g. smpl/SMPL_NEUTRAL.pkl")
    pp.add_argument("--dest", required=True, help="Repo-relative destination path.")
    pp.add_argument("--asset", default=None, help="Asset key (for the JSON result only).")
    pp.add_argument("--source-url", default=None, help="License/download URL (echoed when missing).")
    pp.set_defaults(func=cmd_place)

    args = p.parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as e:
        print("provision_manual_assets: {}".format(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
