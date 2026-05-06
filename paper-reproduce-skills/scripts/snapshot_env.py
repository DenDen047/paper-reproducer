#!/usr/bin/env python3
"""snapshot_env.py

Phase 4 Step 1.4 で実行環境 (host / OS / GPU / CUDA driver / Python) を
reports/environment.json に書き出す。

「どのマシンで再現したか」「telemetry の数字をどの GPU 基準で読むか」を
レポートを開いた瞬間に判断するための情報。取得不可なフィールドは null。
GPU 不在環境では gpus=[]、cuda_version=null。
"""
import datetime
import json
import platform
import socket
import subprocess
import sys
from pathlib import Path


def run(cmd: str) -> str | None:
    try:
        out = subprocess.check_output(
            cmd, shell=True, text=True, stderr=subprocess.DEVNULL
        ).strip()
        return out or None
    except Exception:
        return None


def cpu_model() -> str | None:
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return None


def ram_gb() -> float | None:
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return round(int(line.split()[1]) / 1024 / 1024, 1)
    except Exception:
        return None
    return None


def gpus() -> list[dict]:
    out = run(
        "nvidia-smi --query-gpu=index,name,memory.total,driver_version "
        "--format=csv,noheader,nounits"
    )
    if not out:
        return []
    result = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 4 and parts[0].isdigit():
            result.append({
                "index": int(parts[0]),
                "name": parts[1],
                "memory_total_mb": int(parts[2]),
                "driver_version": parts[3],
            })
    return result


def main() -> int:
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "reports/environment.json")
    env = {
        "hostname": socket.gethostname(),
        "os": run("grep PRETTY_NAME /etc/os-release | cut -d= -f2 | tr -d '\"'"),
        "kernel": platform.release(),
        "cpu": cpu_model(),
        "ram_total_gb": ram_gb(),
        "gpus": gpus(),
        "cuda_version": run("nvidia-smi --query | grep -m1 'CUDA Version' | awk '{print $4}'"),
        "python_version": platform.python_version(),
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(env, indent=2))
    print(f"OK: wrote {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
