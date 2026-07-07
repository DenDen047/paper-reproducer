---
name: manual-asset-provisioner
description: ライセンス登録が必須で自動 DL できない手動 provisioning 資産 (SMPL / SMPL-X / SMPL+H / MANO / FLAME / STAR / SMAL 等) を、ホストの手動資産レジストリ (/manual-assets, read-only) から repo の期待パスへ自動配置する。/reimplement の Phase 3 Step 1 で自動参照される。analysis.json.manual_assets[] を入力に取り、存在すればコピー + .gitignore 追記、欠落なら取得 URL を next_actions に記録して NEVER STOP で続行する。
user-invocable: false
allowed-tools: Bash Read Write Edit Grep
---

# manual-asset-provisioner: 手動資産の自動配置

`analysis.json.manual_assets[]`（repo-analyzer Step 7.7 で検出）を入力に、ホストの**手動資産レジストリ**（`/manual-assets`、read-only マウント）から各モデルを repo の期待パスへ配置する。

正本: `/paper-reproduce-skills/registry/manifest.json`（索引）/ `registry/ASSETS.md`（人間向け）。ヘルパー: `/paper-reproduce-skills/scripts/provision_manual_assets.py`。

## 何が「手動資産」か

SMPL/SMAL 系のように、**ライセンス登録に同意しないと取得できず、トークンでも自動 DL できない**資産。`gated`（HF login 等トークンで解ける）とは別物なので、**probe・自動 DL は行わない**。一次アクションは「レジストリ実在チェック → 配置 or 取得 URL 記録」。

**MUST NOT**: 資産本体を curl / gdown / hf_hub 等で取得しようとする / ミラーから落とす / git にコミットする / 成功アーカイブに含める（= 再配布。ライセンス違反）。

## 手順 (Phase 3 Step 1 の冒頭で実行)

### 0. staging 同期の完了待ち (env `MANUAL_ASSETS_READY_MARKER` 設定時のみ)

bootstrap.sh が正本 (FUSE 上) から staging へ background 同期している場合、env
`MANUAL_ASSETS_READY_MARKER` (= `/manual-assets/.sync-complete`) が渡される。
設定されているときは配置の前に同期完了マーカーを待つ:

```bash
if [ -n "${MANUAL_ASSETS_READY_MARKER:-}" ] && [ ! -f "$MANUAL_ASSETS_READY_MARKER" ]; then
  echo "manual-assets staging sync in progress — waiting (max 60 min)"
  for _i in $(seq 1 120); do
    [ -f "$MANUAL_ASSETS_READY_MARKER" ] && break
    sleep 30
  done
  [ -f "$MANUAL_ASSETS_READY_MARKER" ] || \
    echo "WARN: staging sync marker not found after 60 min — proceeding with files present now"
fi
```

- env 未設定 (= 正本を直接マウントしており staging 不使用) なら即続行。
- マーカー未達でも **NEVER STOP**: 実在するファイルだけで配置を試み、欠落は通常どおり `missing_in_registry` として記録する。

### 1. 入力読込

```bash
jq -c '.manual_assets[]?' reports/analysis.json
```

`manual_assets` が空 / 無しなら本スキルは no-op（即 return）。

### 2. エントリごとに配置 or 記録

各エントリ `{key, display_name, repo_expected_path, registry_candidate, source_url, required_for_claims, ...}` について:

```bash
pixi run python /paper-reproduce-skills/scripts/provision_manual_assets.py place \
  --root /manual-assets \
  --src  "$REGISTRY_CANDIDATE" \
  --dest "$REPO_EXPECTED_PATH" \
  --asset "$KEY" --source-url "$SOURCE_URL"
```

返り値 JSON の `status`:

| status | 意味 | 次の動作 |
|---|---|---|
| `placed` | レジストリに在り、`repo_expected_path` へコピー + `.gitignore` 追記済み | `attempts.tsv` に provisioning 行（result=success, intent に「✓ {display_name} を {dest} へ配置」）。続行 |
| `missing_in_registry` | レジストリに無い | `next_actions[]` に取得手順を記録（下記書式）。`required_for_claims` 非空なら `errors[]` に `manual_asset_missing` も追加。**Phase 3/3.5 は止めない** |
| `placed_empty` | コピーしたが 0 byte（壊れ） | `missing_in_registry` と同様に扱い、`next_actions` に「再 DL」を記録 |
| `invalid_path` | `--src` がレジストリ外 / `--dest` が repo 外に抜けている | パス指定ミス。`registry_candidate` / `repo_expected_path` を確認して正しい相対パスで再実行 |
| `copy_size_mismatch` | コピー結果のサイズが正本と不一致（ディスク不足等） | ディスク容量を確認して再実行。dest には配置されない（tmp+rename のため壊れたファイルは残らない） |

`registry_candidate` が空 / 命名差異がある場合は、`/manual-assets` 配下を `ls` で確認し、manifest の `canonical_files` / `filename_globs` を手がかりに**実在ファイルへマッピングし直してから** `--src` に渡す（`.pkl`↔`.npz`、gender、旧命名 `basicModel_*` 等の差異を吸収）。repo 側の期待ファイル名がレジストリ正規名と違うときは、`--dest` を repo の期待名に合わせる（コピー先名はリネーム可）。

### 3. 配置後の検証

`placed` のものは `repo_expected_path` の実在とサイズ非ゼロを確認し、repo が `model_path` をディレクトリで受ける形式（例: `smplx.create(model_path=...)`）なら、期待ディレクトリ構造（`<dir>/<model_type>/<FILE>`）になっているかを確認する。

## next_actions の書式 (missing 時、§9(b) 準拠)

`$REPORT_LANG` に従い、**そのまま作業手順になる粒度**で 1 項目を生成（`priority` は `required_for_claims` 非空なら `high`、空なら `medium`）。

```
[HIGH] {display_name} モデルが未配置のため {用途} に進めませんでした。
  1. {source_url} でライセンス登録し {ファイル} を DL
  2. ホストに配置:  $MANUAL_ASSETS_DIR/{registry_candidate}
  3. ./bootstrap.sh <repo> を再実行（次回は repo の {repo_expected_path} へ自動配置）
```

`next_actions[]` スキーマ（reimplement Phase 4 Step 1.7）に載せる際:
`{priority, effort:"low", cost:"external_data", action:<上記 1-3 を1文に>, reason:<未達の用途>, command:null}`。

## 配置物の取り扱い (ライセンスガード)

- `place` は配置先を必ず `.gitignore` に追記する（ヘルパーが自動実行）。手動でコピーした場合も**必ず `.gitignore` に入れる**。
- Phase 4 の `git archive HEAD` は tracked のみ収録するため、`.gitignore` 済みなら成功アーカイブに混入しない。Phase 4 で `git status --porcelain` に資産実体が現れていないことを確認する。
- `reports/samples/` にモデル実体（`.pkl`/`.npz`）をコピーしない（samples は入出力データのみ）。
