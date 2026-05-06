#!/usr/bin/env python3
"""training_watcher.py

Phase 3.5 で動かす training プロセスを実 PID 監視し、
NaN/Inf, OOM, artifact 未生成、it/s 低下 を検知する。
検知したら abort_signal_file に tier 分類を書き込み、
training プロセス本体は呼び出し側 (commands/reimplement.md Phase 3.5)
が SIGTERM する。

P3-A2 の self-grep deadlock を避けるため pgrep は使わない。
渡された PID を kill -0 で直接監視する。

入力:
  --pid                training プロセスの実 PID (必須)
  --log                training の stdout+stderr ファイル
  --metrics            reports/training_metrics.json (出力)
  --checkpoint-dir     チェックポイント出力ディレクトリ (artifact 検出用)
  --expected-first-dump-iter  ここを超えたのに chkpnt 0 件なら artifact 不生成と判定
  --abort-signal-file  検知時にここに tier 名を書く

出力 abort_signal_file の中身: "tier1" / "tier2-config" / "tier2-hardware"
"""
import argparse
import datetime
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path


WARMUP_SECONDS = 300  # 起動 5 分は判定しない (init 中に NaN が出ても無視)
SAMPLE_INTERVAL = 30
NAN_STREAK_THRESHOLD = 3
ITPS_DROP_RATIO = 0.5
ITPS_DROP_DURATION_S = 600  # 10 分継続で warning


def is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def sample_gpu() -> dict:
    """nvidia-smi から 1 サンプル取得。失敗は None フィールドで返す。"""
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=5,
        ).strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
        return {"vram_mb": None, "gpu_util_pct": None}
    parts = out.splitlines()[0].split(",")
    if len(parts) < 2:
        return {"vram_mb": None, "gpu_util_pct": None}
    return {"vram_mb": int(parts[0].strip()), "gpu_util_pct": int(parts[1].strip())}


# loss / iter の代表的な行を拾う最小限の正規表現。
# 全 repo を網羅できない前提で、取れない場合は last_iter=None のまま続ける。
LOSS_RE = re.compile(r"loss[:\s=]+([\-\d.]+|nan|inf)", re.IGNORECASE)
ITER_RE = re.compile(r"(?:iter|step|iteration)[:\s=]+(\d+)", re.IGNORECASE)
OOM_RE = re.compile(r"out of memory|CUDA error: out of memory|RC=137", re.IGNORECASE)


def parse_training_log_tail(log_path: Path, tail_lines: int = 200) -> dict:
    if not log_path.exists():
        return {"last_iter": None, "last_loss": None, "is_nan": False, "oom": False}
    try:
        with log_path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 64 * 1024))
            text = f.read().decode("utf-8", errors="replace")
    except OSError:
        return {"last_iter": None, "last_loss": None, "is_nan": False, "oom": False}
    lines = text.splitlines()[-tail_lines:]
    last_iter, last_loss, is_nan = None, None, False
    for line in reversed(lines):
        if last_loss is None:
            m = LOSS_RE.search(line)
            if m:
                v = m.group(1).lower()
                if v in ("nan", "inf"):
                    is_nan = True
                    last_loss = float("nan")
                else:
                    try:
                        last_loss = float(v)
                    except ValueError:
                        pass
        if last_iter is None:
            m = ITER_RE.search(line)
            if m:
                last_iter = int(m.group(1))
        if last_loss is not None and last_iter is not None:
            break
    oom = any(OOM_RE.search(l) for l in lines)
    return {"last_iter": last_iter, "last_loss": last_loss, "is_nan": is_nan, "oom": oom}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--metrics", required=True)
    parser.add_argument("--checkpoint-dir", default=None)
    parser.add_argument("--expected-first-dump-iter", type=int, default=0)
    parser.add_argument("--abort-signal-file", required=True)
    args = parser.parse_args()

    log_path = Path(args.log)
    metrics_path = Path(args.metrics)
    abort_path = Path(args.abort_signal_file)
    ckpt_dir = Path(args.checkpoint_dir) if args.checkpoint_dir else None

    started = time.time()
    samples: list[dict] = []
    warnings: list[str] = []
    nan_streak = 0
    itps_drop_start: float | None = None

    def write_metrics(final: bool = False) -> None:
        if not samples:
            return
        iters = [s["iter"] for s in samples if s.get("iter") is not None]
        wall_clock_min = (time.time() - started) / 60
        if len(iters) >= 2 and iters[-1] != iters[0] and (samples[-1]["t_unix"] - samples[0]["t_unix"]) > 0:
            iter_per_sec = (iters[-1] - iters[0]) / (samples[-1]["t_unix"] - samples[0]["t_unix"])
        else:
            iter_per_sec = None
        peak_vram = max((s.get("vram_mb") or 0) for s in samples)
        utils = [s["gpu_util_pct"] for s in samples if s.get("gpu_util_pct") is not None]
        mean_util = sum(utils) / len(utils) if utils else None
        metrics = {
            "wall_clock_min": round(wall_clock_min, 2),
            "iter_per_sec_mean": round(iter_per_sec, 2) if iter_per_sec else None,
            "peak_vram_mb": peak_vram or None,
            "mean_gpu_util_pct": round(mean_util, 1) if mean_util else None,
            "warnings": warnings,
            "samples": samples[-2000:],  # 上限を切って巨大化を防ぐ
            "finalized": final,
        }
        metrics_path.parent.mkdir(parents=True, exist_ok=True)
        metrics_path.write_text(json.dumps(metrics, indent=2))

    def signal_abort(tier: str, reason: str) -> None:
        abort_path.write_text(tier)
        warnings.append(f"abort: {tier} ({reason})")
        write_metrics(final=True)

    while is_alive(args.pid):
        if abort_path.exists():
            break  # 外部から abort 指示
        gpu = sample_gpu()
        log_state = parse_training_log_tail(log_path)
        elapsed = time.time() - started
        sample = {
            "t": datetime.datetime.utcnow().isoformat() + "Z",
            "t_unix": time.time(),
            "iter": log_state["last_iter"],
            **gpu,
        }
        samples.append(sample)

        if elapsed >= WARMUP_SECONDS:
            # 1) NaN/Inf streak
            if log_state["is_nan"]:
                nan_streak += 1
                if nan_streak >= NAN_STREAK_THRESHOLD:
                    signal_abort("tier2-config", "loss NaN/Inf 3x consecutive")
                    return 0
            else:
                nan_streak = 0

            # 2) OOM
            if log_state["oom"]:
                signal_abort("tier2-hardware", "OOM detected in training log")
                return 0

            # 3) Artifact 未生成
            if (
                ckpt_dir is not None
                and log_state["last_iter"] is not None
                and log_state["last_iter"] > args.expected_first_dump_iter
                and ckpt_dir.exists()
            ):
                has_ckpt = any(p for p in ckpt_dir.rglob("*") if p.is_file())
                if not has_ckpt:
                    signal_abort(
                        "tier1",
                        f"no checkpoint produced past iter {log_state['last_iter']}",
                    )
                    return 0

            # 4) it/s 低下 (warning のみ)
            recent = [s for s in samples if s["t_unix"] > time.time() - 300 and s.get("iter")]
            past = [s for s in samples if s["t_unix"] <= time.time() - 300 and s.get("iter")]
            if len(recent) >= 2 and len(past) >= 2:
                def _ips(arr):
                    di = arr[-1]["iter"] - arr[0]["iter"]
                    dt = arr[-1]["t_unix"] - arr[0]["t_unix"]
                    return di / dt if dt > 0 else None
                cur_ips, past_ips = _ips(recent), _ips(past)
                if cur_ips and past_ips and cur_ips < past_ips * ITPS_DROP_RATIO:
                    if itps_drop_start is None:
                        itps_drop_start = time.time()
                    elif time.time() - itps_drop_start > ITPS_DROP_DURATION_S:
                        warnings.append(f"it/s dropped to {cur_ips:.2f} (was {past_ips:.2f})")
                        itps_drop_start = None  # 1 回 warn したらリセット
                else:
                    itps_drop_start = None

        if len(samples) % 4 == 0:  # 約 2 分ごとにファイル更新
            write_metrics(final=False)
        time.sleep(SAMPLE_INTERVAL)

    write_metrics(final=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
