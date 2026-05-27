# Changelog

本ファイルは [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) の形式に従い、
バージョニングは [Semantic Versioning 2.0.0](https://semver.org/lang/ja/) に準拠する。

## [Unreleased]

## [0.1.5] - 2026-05-27

### Added — host の HuggingFace 認証 / キャッシュをコンテナへ伝播

一部の gated モデル (facebook 製等) は申請済みアカウントのトークンが無いと
DL できず、再現フローが `gated` → partial / Tier 3 で止まっていた。host で
既に許諾を得ているアカウントの正規アクセスをコンテナへ引き継ぎ、これを解消する
(gated 制約の「回避」ではなく本人アクセスの引き継ぎ)。

- **`bootstrap.sh`**: GH_TOKEN と同型の伝播を追加。
  - host の `${HF_HOME:-~/.cache/huggingface}` を `/home/claude/.cache/huggingface`
    に bind-mount し、token ファイルと `hub/`・`xet/` モデルキャッシュを共有。
    gated モデルの host 既 DL 分を再利用し再 DL を避ける (claude user は host UID
    に揃えてあるので読み書き可)。
  - `HF_TOKEN` → `HUGGING_FACE_HUB_TOKEN` → `~/.cache/huggingface/token` →
    `~/.huggingface/token` の順で token を解決し、見つかれば `-e HF_TOKEN`
    (値はコマンドラインに出さず env 名のみ) で渡す。
  - host に HF 認証もキャッシュも無ければ何も渡さず従来どおり public DL のみ。
  - 単一・バッチ両モードの `docker run` に適用。バッチモードでは cache マウントが
    token ファイルを含むため、`-e HF_TOKEN` の tmux 環境継承制約に当たっても認証が効く。

### Implications

- 効かせるには host で `huggingface-cli login` (または `HF_TOKEN` 設定) が必要。
- この変更は `bootstrap.sh` のみで Dockerfile を触らないため、イメージ再ビルドは不要。

## [0.1.4] - 2026-05-27

### Fixed — 再現コンテナに gh / jq を同梱し Phase 4 の Issue 検索を有効化

再現コンテナ (`Dockerfile`) が `gh` / `jq` を含まず、`/reimplement` 実行中に
「gh/jq が無く Phase 4 では関連 Issue 検索をスキップしていました」が発生していた。
`jq` は `experiment-loop/SKILL.md` 内で `github_slug` /
`training_recovery.resume_arg` の抽出にラッパなしで直接使われており、不在時は
Issue 検索だけでなく resume 判定も静かに失敗していた (影響範囲は Issue 検索より広い)。

- **`paper-reproduce-skills/Dockerfile`**: `pixi global install` に `gh jq` を追加。
  pixi-only ポリシー準拠で conda-forge から導入 (apt/brew は使わない)。
- **`bootstrap.sh`**: コンテナは `~/.config/gh` をマウントしないため `gh` を
  入れるだけでは未認証 (`gh auth status` 失敗 → `no-auth` でスキップ) になる。
  host の認証済み `gh` から `gh auth token` を取り出し `GH_TOKEN` env として
  コンテナへ伝播する (値はコマンドラインに出さず env 名のみ渡す、`ANTHROPIC_API_KEY`
  と同じ流儀)。host に gh が無い / 未認証なら何も渡さず従来どおり graceful skip に
  フォールバック。単一・バッチ両モードの `docker run` に適用。
- 適用には Dockerfile の再ビルドが必要 (`./bootstrap.sh --rebuild ...`)。

## [0.1.3] - 2026-05-08

### Added — P0-E ポテンシャル最大化原則

「`/reimplement` の最終成果物は **論文ポテンシャルの実機提示** であり
smoke test ("it works") ではない」を明文化した新原則 `P0-E` を確立。
Phase 3 で Claude が時間短縮のため `num_inference_steps` / `iterations` /
`num_views` 等をデフォルト値から減らし、「動いた」だけで success と判定して
論文デフォルトでの再実行を `next_actions` 任せにする運用を抑止する。

#### Added (B: 原則の確立)

- **`reimplement/SKILL.md` 核心原則**: 新規 `P0-E ポテンシャル最大化` 節。
  目標優先順位 (claim 再現 > 論文デフォルト引数 > 実行時間最小化) と
  「実行時間は tier 判定に影響しない」(数時間かかっても tier0/1/2 にならない)
  ことを明記
- **`experiment-loop/SKILL.md` NEVER STOP 直下**: P0-E への参照と
  「`"to save time"` / `"for quick smoke"` は intent 禁止」を追加
- **`reimplement/SKILL.md` Step 1.7 next_actions**: `status=success` の
  next_action に「論文デフォルトで再実行」を載せることを **MUST NOT** 化
  (= 自分で削った物を user に丸投げする運用を禁止)。`cost=free` で
  「デフォルトに戻す」項目は禁止、`cost=gpu_upgrade` (= ハード制約での
  正当な縮小の補完) なら可

### Fixed — P0-E の手続き化 + サンプル表示の修正

#### Fixed (D: Phase 3 Step 3 の手続き化)

P0-E 原則を文書化しただけでは Phase 3 実行中に Claude が読み戻さず、
依然として `--num-views 4` / `--texture-size 256` のような reduced-param
で smoke 完了 → success 判定する挙動が再現された (例: ReLi3D)。
「読まれない原則は存在しないのと同じ」という LLM 駆動の特性に対し、
**成果物 + Tier 0 違反** で手続き化することで抑止。

- **`reimplement/SKILL.md` Phase 3 Step 3** を 2 sub-step に分割:
  - **Step 3a**: `reports/_paper_default_args.json` を**物理的成果物として
    必ず作る** (作らずに Step 3b に進むのは **Tier 0 違反**)。README /
    `examples/` / `configs/inference*.yaml` から全推論引数のデフォルト値を
    抽出し、`{value, source}` 形式で保存
  - **Step 3b**: 最初の attempt は paper-default 全値必須、
    `attempts.tsv.intent` に `"P0-E paper-default attempt; args from {source}"`
    を必須含有。reduced-param は paper-default success 後の追加 attempt
    としてのみ許可。`attempts.tsv` に paper-default success 行が無いまま
    Phase 4 へ進むのも **Tier 0 違反**

#### Fixed (3D / video サンプルで入力画像が表示されない)

- **`templates/RENDERING.md`**: `type=mesh` / `gaussian_splat` /
  `point_cloud` / `video` の HTML テンプレが `input_paths` を一切
  参照していなかった (例: PartCrafter / Geometry-Grounded-GS で
  `input_paths` が JSON にあるのに HTML 上に表示なし)
- 4 type 共通の「入力サムネイル共通ブロック」を新設し、各 type 雛形から
  コメントで参照させる。CSS (`sample-grid-2/3`) は既存、schema / Python
  script は無変更。既存 `report.json` は変更不要 — HTML 再レンダリング
  だけで入力画像が表示される

#### Fixed (`.glb` / `.gltf` mesh が viewer で上下反転)

- **`sample-embedder/SKILL.md` Step 4.5**:
  `analysis.json.coord_convention.world="opencv"` を `sample-embedder` が
  そのまま `metadata.coord_convention` に転記し、viewer が X 軸 180°
  回転を適用していた (例: ReLi3D)。論文の **内部** convention (training
  時の camera 座標系) と出力ファイルの convention の混同
- 優先順位を更新: `type=mesh` かつ拡張子が `.glb` / `.gltf` の場合は
  必ず `opengl` を採用 (glTF 2.0 spec §3.3 が Y-up を強制するため、
  論文の内部 convention は exporter が自動変換済み)。`.ply` / `.obj` の
  既存ヒューリスティクスは変更なし
- 既存の glb 系レポートは `metadata.coord_convention="opencv"` →
  `"opengl"` に手動修正で即修復可

## [0.1.2] - 2026-05-06

### Fixed — v0.1.1 regression の修正 (B+C hybrid)

v0.1.1 で導入した schema gate と分類厳格化が **過度に保守的** に作用し、
HKUST-SAIL/Geometry-Grounded-Gaussian-Splatting の再現で v0.1.0 では達成
していた `Chamfer 0.375 mm` を達成できなくなる退行が発生。原因は
`data_acquisition_table[].category` の draft 値 (= landing page を probe
しただけの粗い分類) を信用して **試行ゼロのまま Phase 3.5 を skip** していたこと。

「介入数 0」だけが最適化され、本来の core value である **「介入があっても
最終的に claim 達成まで自律試行する」** が損なわれていた。

#### Changed (B: surgical fix - 分類を積極化)

- **`repo-analyzer/SKILL.md` Step 7.5 (probe する URL の選び方)**: README の
  landing page だけで probe を終わらせず、実体の direct DL URL を辿って再 probe
  する原則を新設。GDrive folder URL / 直 HTTP archive / HF API の各典型を
  網羅した表を追加。default bias を `auto-fetch` 寄りに変更。3 件の MUST NOT
  を追加 (landing page だけで分類 / "manual click-through" prose を根拠に降格 /
  preprocess: external_tool を理由に分類 — preprocess は取得性とは独立)。

#### Changed (C: Phase 3.5 強制起動)

- **`skills/reimplement/SKILL.md` Phase 3 Step 1 dataset table**: `assisted` /
  `gated` を「次 actions に書いて諦め」から「**必ず取得を試行する**」に変更。
  3 回まで attempt loop で gdown / curl / hf_api を実行。`blocked` でも 1 回
  試してから errors[] に追加する設計。
- **`skills/reimplement/SKILL.md` Phase 3.5 起動判定**: `train_required` /
  `train_optional` + `paper_claims` 非空なら **dataset 取得状況に関わらず必ず
  Phase 3.5 を起動する** MUST に変更。dataset 取得は Phase 3.5 内の attempt loop
  で繰り返し試行 (= Phase 3 で取れなくても起動を諦めない)。4 件の MUST NOT を
  追加して退行パターンを明文化。

#### Changed (P2-B 補強)

- **`experiment-loop/SKILL.md` データ取得失敗の分類**: tier3 への昇格は
  「実際に試行してから」を明記。試行ゼロでの tier3 を MUST NOT 化。`Direct DL
  URL 抽出失敗 (landing page だけ)` を tier1 扱いとして新設し、folder ID 抽出 /
  README grep で direct URL を抽出して再試行する経路を追加。`required_for_claims`
  非空の GDrive レート制限は ScheduleWakeup で N 時間後再試行を schedule。

### 期待される behaviour (回帰テスト基準)

HKUST-SAIL/Geometry-Grounded-Gaussian-Splatting で:
- Phase 3.5 が必ず起動する (smoke のみで終わらない)
- DTU preprocessed (GDrive folder) と DTU Official Points (直 HTTP) が
  `auto-fetch` で取得される (landing page だけで `assisted` 化されない)
- TnT は真に `assisted` (web form) であれば次 actions に手順記載、ただし
  DTU だけで Chamfer eval を完走 → `claims_verification[].status` が
  `matched` または `within_tolerance`
- 結果として v0.1.0 の Chamfer ~0.4 mm 帯を再現

## [0.1.1] - 2026-05-06

### Changed — 判断ミス再発防止のための構造改修

実環境再現で確認された 4 件の判断ミス (`samples.items[].type=mesh + .ply`、`paper_claims=[]` 無理由、`reproduction_mode=train_optional` 誤判定、`feasibility.blockers` の string ↔ object スキーマドリフト) を構造的に防ぐための refactor。Codex (GPT-5.5 xhigh) の review を反映。

#### Added

- **JSON Schema gate** (`paper-reproduce-skills/schemas/`): Phase 1 (`analysis.json`) と Phase 4 Step 2 (`report.json`) で `check-jsonschema` による機械検証を必須化。
  - `analysis.schema.json`: `feasibility.blockers` を object 配列 (`{id, detail, severity?, recovery?}`) に固定。`paper_claims=[]` のとき `claims_extraction.status` enum (`extracted` / `no_quantitative_claims` / `paper_unavailable` / `extraction_failed`) を必須化。`reproduction_mode=train_*` のとき `training_recovery` を必須化。
  - `report.schema.json`: `samples.items[].type=mesh` の output を `.glb` / `.gltf` / `.obj` のみに制約 (P1-A 構造的強制)。3DGS 由来の video には `metadata.ply_compatibility` を必須化。
- **`scripts/snapshot_env.py`**: Phase 4 Step 1.4 のインライン Python (~50 行) を独立スクリプトに分離。
- **`skills/reimplement/SKILL.md`**: 旧 `commands/reimplement.md` (1240 行) を「上位 = exit contract、下位 = how」モデルで再構成 (523 行、58% 削減)。`disable-model-invocation: true` で副作用大の skill の auto-fire を抑制。

#### Fixed

- **`repo-analyzer/SKILL.md` Step 0.6.5 (新設)**: Paper Claims 抽出を独立 phase として明文化。空配列を黙って返すのを禁止し、`claims_extraction.status` enum + `evidence` を必須化。
- **`repo-analyzer/SKILL.md` Step 7.6**: `reproduction_mode` 判定を `paper_claims` 起点に厳格化。「checkpoint URL + train script の両方ある」だけで `train_optional` と判定する短絡を MUST NOT として禁止。
- **`repo-analyzer/SKILL.md` Step 10**: `feasibility.blockers` を `[{id, detail, severity?, recovery?}]` の object 配列に統一 (旧 `["string"]` 形式とのドリフト根絶)。

#### Removed

- **`commands/reimplement.md`**: Claude Code の commands→skills 統合方針および Anthropic best practices (SKILL.md body < 500 行) に従い完全削除。`/reimplement` (= `/paper-reproduce:reimplement`) は `skills/reimplement/SKILL.md` として引き続き起動可能。
- `paper-reproduce-skills/commands/` ディレクトリ自体を削除。

### Changed (Docker)

- `Dockerfile`: `pixi global install` に `check-jsonschema` を追加 (Phase 1 / Phase 4 schema gate で使用)。

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

[Unreleased]: https://github.com/DenDen047/paper-reproducer/compare/v0.1.5...HEAD
[0.1.5]: https://github.com/DenDen047/paper-reproducer/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/DenDen047/paper-reproducer/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/DenDen047/paper-reproducer/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/DenDen047/paper-reproducer/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/DenDen047/paper-reproducer/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/DenDen047/paper-reproducer/releases/tag/v0.1.0
