#!/usr/bin/env python3
"""render_gaussian_video.py

3D Gaussian 学習結果 (PLY) を動画 (mp4) に焼き付ける薄いラッパー。
派生 3DGS (2DGS / Scaffold-GS / GoF / GeoGS / Mip-Splatting 等) は
Three.js の gaussian-splats-3d viewer がスキーマ非互換でレンダリング失敗
するため、再現結果の主出力を動画にして「最低限見られる」状態を保証する。

実行戦略 (順に試行、最初に成功したものを採用):
  1. repo の render.py を呼ぶ (paper 視点と一致)
  2. <repo>/scripts/render_video.py / eval.py --visualize / demo.py
  3. orbit camera を作って repo の Camera クラスに食わせる最小スクリプト

本スクリプトは「render する」より「ffmpeg で連結する」と「PLY 互換性検証」
を担当し、render の実コマンド検出は呼び出し元 (sample-embedder) が
analysis.json と repo の grep 結果から決める。

入力:
  --frames-dir         render.py が PNG を吐いたディレクトリ
  --output-mp4         書き出し mp4 パス (~12 MB target)
  --fps                既定 30
  --target-mb          fallback の閾値、既定 12 (frame 数は削らない方針)
  --check-ply          指定すると PLY 互換性検証だけ実行して JSON を stdout に出す
出力:
  --check-ply 指定時:  {"is_standard": bool, "missing": [...], "extra": [...], "reason": "..."}
  通常:               mp4 を書き出し、stdout に最終サイズ MB を出す
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


REQUIRED_3DGS_PROPS = {
    "x", "y", "z",
    "f_dc_0", "f_dc_1", "f_dc_2",
    "scale_0", "scale_1", "scale_2",
    "rot_0", "rot_1", "rot_2", "rot_3",
    "opacity",
}


def parse_ply_header(path: Path) -> set[str]:
    """ascii / binary の両形式で property 名を取り出す。"""
    props: list[str] = []
    with path.open("rb") as f:
        for line in f:
            decoded = line.decode("ascii", errors="ignore").strip()
            if decoded == "end_header":
                break
            m = re.match(r"property\s+\S+\s+(\S+)", decoded)
            if m:
                props.append(m.group(1))
    return set(props)


def check_ply_compatibility(path: Path) -> dict:
    props = parse_ply_header(path)
    missing = sorted(REQUIRED_3DGS_PROPS - props)
    extra = sorted(props - REQUIRED_3DGS_PROPS - {"red", "green", "blue", "alpha", "nx", "ny", "nz"})
    is_standard = not missing
    # 派生のヒューリスティック (LLM が reason をもう少し具体化するための材料を返す)
    reason = None
    if not is_standard:
        if "scale_2" in missing and "scale_0" in props:
            reason = "missing scale_2 (likely 2DGS / planar gaussian)"
        elif any(p.startswith(("feature_dc_", "offset_")) for p in extra):
            reason = "unexpected scaffold features (Scaffold-GS variant)"
        elif any(p.startswith("frequency_") for p in extra):
            reason = "unexpected mip features (Mip-Splatting variant)"
        elif missing:
            reason = f"missing standard props: {missing[:5]}"
    return {
        "is_standard": is_standard,
        "missing": missing,
        "extra": extra[:30],  # 出力肥大防止
        "reason": reason,
    }


def encode_mp4(frames_dir: Path, output_mp4: Path, fps: int, target_mb: float) -> float:
    """PNG glob を mp4 に焼き、target_mb 超過なら crf / 解像度を順に下げる。

    NOTE: frame 数は **絶対に削らない**。frame を削ると 60 frame / 2 秒のスナップショット
    動画になり「滑らかな orbit rendering」という主目的を壊す (ユーザー実フィードバック由来)。
    quality / resolution は妥協してよいが motion の連続性は守る。
    """
    pattern = str(frames_dir / "*.png")
    if not list(frames_dir.glob("*.png")):
        # 階層 1 つ深いところを試す (renders/00000.png のような構造)
        candidates = list(frames_dir.rglob("*.png"))
        if not candidates:
            print(f"FAIL: no PNG frames under {frames_dir}", file=sys.stderr)
            sys.exit(2)
        pattern = str(candidates[0].parent / "*.png")

    fallbacks = [
        # (description, extra_args)
        ("crf=23 1080p", ["-crf", "23"]),
        ("crf=28 1080p", ["-crf", "28"]),
        ("crf=28 720p",  ["-crf", "28", "-vf", "scale=1280:720"]),
        ("crf=32 720p",  ["-crf", "32", "-vf", "scale=1280:720"]),
    ]
    output_mp4.parent.mkdir(parents=True, exist_ok=True)
    last_size_mb = float("inf")
    for desc, extra in fallbacks:
        cmd = [
            "ffmpeg", "-y", "-framerate", str(fps),
            "-pattern_type", "glob", "-i", pattern,
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            *extra,
            str(output_mp4),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"WARN: ffmpeg failed at {desc}: {result.stderr[-300:]}", file=sys.stderr)
            continue
        last_size_mb = output_mp4.stat().st_size / (1024 * 1024)
        if last_size_mb <= target_mb:
            return last_size_mb
        print(f"INFO: mp4 {last_size_mb:.1f} MB > target {target_mb} MB, trying {desc} fallback", file=sys.stderr)
    return last_size_mb


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-ply", default=None, help="PLY 互換性検証だけ行う")
    parser.add_argument("--frames-dir", default=None)
    parser.add_argument("--output-mp4", default=None)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--target-mb", type=float, default=12.0)
    args = parser.parse_args()

    if args.check_ply:
        result = check_ply_compatibility(Path(args.check_ply))
        print(json.dumps(result, indent=2))
        return 0

    if not (args.frames_dir and args.output_mp4):
        print("FAIL: --frames-dir and --output-mp4 are required for encode", file=sys.stderr)
        return 2

    size_mb = encode_mp4(Path(args.frames_dir), Path(args.output_mp4), args.fps, args.target_mb)
    print(f"{size_mb:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
