#!/usr/bin/env python3
"""probe_dataset.py

dataset URL の reachability を統一 IF で probe し JSON を返す。
repo-analyzer Step 7.5 から呼ばれ data_acquisition_table[i].probe を埋める。

入力: --url (HTTP / GDrive / HuggingFace の dataset URL)
出力: --output に JSON ({method, reachable, checked_at, evidence, content_length})

LLM が draft で出した category を probe 結果で上書きするための情報を返す。
gdown / huggingface_hub / curl の subprocess は失敗しても exit 0 で
reachable=false の JSON を書く (再現フローを止めない)。
"""
import argparse
import datetime
import json
import re
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path


def detect_method(url: str) -> str:
    """URL 形状から probe 方法を判定。

    huggingface > gdown > http の順で具体性が高いものを選ぶ。
    """
    host = urllib.parse.urlparse(url).hostname or ""
    if "huggingface.co" in host or url.startswith("hf://"):
        return "hf_api"
    if "drive.google.com" in host or "docs.google.com" in host:
        return "gdown_dry_run"
    if url.startswith(("http://", "https://")):
        return "http_head"
    return "none"


def probe_http(url: str) -> dict:
    """curl -ILs で HEAD。content-length と最終ステータスを取り出す。"""
    try:
        out = subprocess.run(
            ["curl", "-ILsm", "10", "-A", "paper-reproduce-probe/1.0", url],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return {"reachable": False, "evidence": f"curl failed: {e}"}
    text = out.stdout or ""
    # 最後の HTTP ステータス行 (リダイレクト連鎖の終端) を採用
    status_lines = re.findall(r"^HTTP/[\d.]+ (\d+)", text, re.MULTILINE)
    final_status = int(status_lines[-1]) if status_lines else None
    cl_match = re.findall(r"^content-length:\s*(\d+)", text, re.MULTILINE | re.IGNORECASE)
    content_length = int(cl_match[-1]) if cl_match else None
    reachable = final_status is not None and 200 <= final_status < 400
    return {
        "reachable": reachable,
        "http_status": final_status,
        "content_length": content_length,
        "evidence": f"HTTP {final_status}, content-length={content_length}",
    }


def probe_gdown(url: str) -> dict:
    """gdown を quiet dry-run 相当で叩いて到達性のみ確認。

    gdown は --dry-run を持たないため、`gdown --quiet --no-cookies -O /dev/null`
    を short-timeout で実行し、最初のチャンク取得まで通れば reachable とみなす。
    """
    if shutil.which("gdown") is None:
        return {"reachable": False, "evidence": "gdown not installed"}
    is_folder = "/folders/" in url
    cmd = ["gdown", "--no-cookies", "--quiet"]
    if is_folder:
        cmd += ["--folder", "--remaining-ok", url]
    else:
        cmd += [url, "-O", "/dev/null"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        # GDrive はレート制限時に応答自体が遅延するので timeout=blocked と扱う
        return {"reachable": False, "evidence": "gdown timeout (likely rate-limited)"}
    err = (out.stderr or "")[:500]
    if out.returncode == 0:
        return {"reachable": True, "evidence": "gdown ok"}
    if "domain administrator" in err or "rate" in err.lower() or "quota" in err.lower():
        return {"reachable": False, "evidence": f"gdown rate-limited: {err.strip()}"}
    if "permission" in err.lower() or "access" in err.lower():
        return {"reachable": False, "evidence": f"gdown auth/permission: {err.strip()}"}
    return {"reachable": False, "evidence": f"gdown error rc={out.returncode}: {err.strip()}"}


def probe_hf(url: str) -> dict:
    """huggingface_hub.HfApi.repo_info でリポ存在 + サイズ合計を取得。"""
    # URL から repo_id を抽出。例:
    # https://huggingface.co/datasets/foo/bar -> repo_type=dataset, repo_id=foo/bar
    # https://huggingface.co/foo/bar          -> repo_type=model,   repo_id=foo/bar
    m = re.match(
        r"https?://huggingface\.co/(datasets/|spaces/)?([^/?#]+/[^/?#]+)",
        url,
    )
    if not m:
        return {"reachable": False, "evidence": f"cannot parse hf url: {url}"}
    prefix, repo_id = m.group(1), m.group(2)
    repo_type = "dataset" if prefix == "datasets/" else ("space" if prefix == "spaces/" else "model")
    try:
        from huggingface_hub import HfApi  # type: ignore
    except ImportError:
        return {"reachable": False, "evidence": "huggingface_hub not installed"}
    try:
        info = HfApi().repo_info(repo_id, repo_type=repo_type, files_metadata=True)
    except Exception as e:
        msg = str(e)
        if "401" in msg or "gated" in msg.lower() or "authentication" in msg.lower():
            return {"reachable": False, "evidence": f"hf gated/auth: {msg[:200]}"}
        return {"reachable": False, "evidence": f"hf error: {msg[:200]}"}
    total = sum(getattr(s, "size", 0) or 0 for s in (info.siblings or []))
    return {
        "reachable": True,
        "content_length": total or None,
        "evidence": f"hf {repo_type} {repo_id}, files={len(info.siblings or [])}, total_bytes={total}",
    }


METHOD_DISPATCH = {
    "http_head": probe_http,
    "gdown_dry_run": probe_gdown,
    "hf_api": probe_hf,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument(
        "--method",
        choices=["auto", "http_head", "gdown_dry_run", "hf_api", "none"],
        default="auto",
    )
    parser.add_argument("--output", required=True, help="JSON 出力パス")
    args = parser.parse_args()

    method = detect_method(args.url) if args.method == "auto" else args.method
    if method == "none":
        result = {"method": "none", "reachable": False, "evidence": "no probe method"}
    else:
        try:
            partial = METHOD_DISPATCH[method](args.url)
        except Exception as e:
            partial = {"reachable": False, "evidence": f"probe crashed: {e}"}
        result = {"method": method, **partial}

    result["checked_at"] = datetime.datetime.utcnow().isoformat() + "Z"
    Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False))
    return 0  # 失敗時も exit 0 (再現フローを止めない、reachable=false で表現する)


if __name__ == "__main__":
    sys.exit(main())
