# Changelog

本ファイルは [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) の形式に従い、
バージョニングは [Semantic Versioning 2.0.0](https://semver.org/lang/ja/) に準拠する。

## [Unreleased]

## [0.1.0] - 2026-05-06

### Added — 初回リリース

CV 論文の GitHub リポジトリを Claude Code エージェントで全自動再現する Claude Code プラグインの最初の公開版。

このリリースのハイライト:

- **6-Type 依存分類 → Pixi 統一**: environment.yml / pyproject.toml / requirements.txt / setup.py / Dockerfile-only / 依存ファイル無し の 6 タイプを自動判定し、すべて Pixi に変換することで `pixi.lock` ベースの完全再現性を確保
- **Experiment Loop + 監査ログ**: `pixi install` と推論実行のエラーを診断して自動修正・再試行し、全試行を `attempts.tsv` + `report.json` に機械可読で記録。再現失敗もログとして資産化
- **Docker サンドボックス + Feasibility Gate**: 論文コードを host から隔離した pixi 公式コンテナで実行し、Phase 2 前に GPU arch / VRAM / 認証情報を判定して **動かない環境では着手前に失敗判定**

#### 主要機能

- **`/reimplement` slash command**: README + 依存ファイル解析 → Pixi 環境構築 → 推論実行 → レポート生成までを単一コマンドで自動実行
- **6-Type 依存分類** (`repo-analyzer`): environment.yml / pyproject.toml / requirements.txt / setup.py / Dockerfile-only / dependency-less の 6 タイプを判定し、すべて Pixi に収束させる変換戦略を選択
- **Experiment Loop** (`experiment-loop`): pixi install が通り推論が走るまでエラー診断 → 修正 → 再試行を自動で繰り返し、全試行を `attempts.tsv` に記録
- **CUDA / GPU arch 互換性チェック**: GPU アーキテクチャ非互換を Phase 2 前に検出する Feasibility Gate と Arch Upgrade Ladder
- **再現レポート出力**: `report.html` (`REPORT_LANG=ja|en` で言語切替) / `report.json` (機械可読) / `analysis.json` / `attempts.tsv` / `environment.json` / 入出力サンプル / 状態スナップショット (tar.gz) をホスト側に永続化
- **Docker サンドボックス実行**: `ghcr.io/prefix-dev/pixi` ベースのコンテナ内で全自動実行。host UID/GID 同期、TERM 伝播、symlink target マウント等の調整済み
- **バッチモード**: 複数 URL / `--repos <file>` で並列再現。GPU 排他 (`--gpus device=N` + `flock`) と tmux ウィンドウ起動

#### 補助機能

- 失敗時に同リポジトリの関連 Issue / PR を集約表示
- 失敗時に主因 1 行と回復可能性バッジをサマリーに表示
- partial / failed でも tar.gz アーカイブを生成
- 点群ビューワにポイントサイズスライダ
- 座標系規約の自動検出による 3D viewer の上下逆さま表示の防止
- mesh glb 強制 + 3DGS 動画化 + PLY subsample のサンプル生成
- Phase 3.5 の claims verification、GDrive レート制限ハンドリング

### Changed

- `paper-reproduce-skills/.claude-plugin/plugin.json`: `version` を `1.0.0` (既定値) から `0.1.0` に修正、`license` を `MIT` から `Apache-2.0` に変更

### Documentation

- `LICENSE` (Apache 2.0) を追加
- README.md に License 節を追加 (再現対象コードは元ライセンス遵守 / Pro 機能は別途販売予定の注記)

[Unreleased]: https://github.com/DenDen047/paper-reproducer/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/DenDen047/paper-reproducer/releases/tag/v0.1.0
