# report.html レンダリング規則 (i18n + 動的ブロック)

`commands/reimplement.md` Phase 4 Step 3 から参照される詳細仕様。テンプレート (`templates/report.html`) のプレースホルダのうち、**i18n 系** と **動的 HTML ブロック** (overview / problem / environment / usage / samples / next_actions) の組み立て方を定義する。

**Content placeholders** (`{{REPO_NAME}}`, `{{ATTEMPTS_ROWS}}` 等の動的データ由来の値) と **基本フロー** (テンプレ複製 → 言語解決 → 置換 → finalize_report.py) は本ファイルではなく `commands/reimplement.md` Step 3 を参照。

## 目次

- [i18n placeholders 表](#i18n-placeholders-chrome-文字列i18njsonlang_code-由来)
- [動的レンダリング側で使う dict キー](#動的レンダリング側で使う-dict-キー)
- [overview ブロック](#overview-ブロックのレンダリング)
- [problem ブロック](#problem-ブロックのレンダリング)
- [environment ブロック](#environment-ブロックのレンダリング)
- [usage ブロック (quickstart / advanced / developer)](#usage-ブロックのレンダリング)
- [samples ブロック (image / 3D / video)](#samples-ブロックのレンダリング)
- [next_actions ブロック](#next_actions-ブロックのレンダリング)
- [HTML エスケープ規則](#html-エスケープ共通)

## i18n placeholders（chrome 文字列、`i18n.json[$LANG_CODE]` 由来）

| プレースホルダー | dict キー |
|---|---|
| `{{HTML_LANG}}` | `html_lang` |
| `{{T_TITLE_PREFIX}}` | `title_prefix` |
| `{{T_META_GENERATED}}` | `meta_generated` |
| `{{T_H2_SUMMARY}}` / `{{T_H2_ENVIRONMENT}}` / `{{T_H2_OVERVIEW}}` / `{{T_H2_PROBLEM}}` / `{{T_H2_USAGE}}` / `{{T_H2_NEXT_ACTIONS}}` / `{{T_H2_SAMPLES}}` / `{{T_H2_ATTEMPTS}}` / `{{T_H2_ARTIFACTS}}` / `{{T_H2_PIXI}}` / `{{T_H2_ERRORS}}` | `h2_*` |
| `{{T_H3_QUICKSTART}}` / `{{T_H3_ADVANCED}}` / `{{T_H3_DEVELOPER}}` | `h3_*` |
| `{{T_LABEL_STATUS}}` / `{{T_LABEL_DEP_TYPE}}` / `{{T_LABEL_TOTAL_ATTEMPTS}}` / `{{T_LABEL_TOTAL_DURATION}}` | `label_*` |
| `{{T_TH_NUM}}` / `{{T_TH_COMMIT}}` / `{{T_TH_PHASE}}` / `{{T_TH_ACTION}}` / `{{T_TH_INTENT}}` / `{{T_TH_RESULT}}` / `{{T_TH_TIER}}` / `{{T_TH_ERROR_SUMMARY}}` / `{{T_TH_DURATION_S}}` | `th_*` |
| `{{T_LEGEND_SUMMARY}}` / `{{T_LEGEND_PHASE_HEADING}}` / `{{T_LEGEND_TIER_HEADING}}` / `{{T_LEGEND_PHASE0_DESC}}` … `{{T_LEGEND_PHASE4_DESC}}` / `{{T_LEGEND_TIER0_DESC}}` / `{{T_LEGEND_TIER1_DESC}}` / `{{T_LEGEND_TIER2_CONFIG_DESC}}` / `{{T_LEGEND_TIER2_HARDWARE_DESC}}` / `{{T_LEGEND_TIER3_DESC}}` / `{{T_LEGEND_DASH_DESC}}` | `legend_*` |
| `{{T_WARN_FILE_PROTOCOL_TITLE}}` / `{{T_WARN_FILE_PROTOCOL_BODY}}` | `warn_file_protocol_*` |
| `{{T_FOOTER_GENERATED_BY}}` | `footer_generated_by`（`{plugin_name}` を `paper-reproduce` に、`{version}` を `plugin.json.version` に展開してから挿入） |
| `{{I18N_JSON_INLINE}}` | strings dict 全体を `JSON.stringify` 相当（`<` `>` `&` をエスケープ済み）。JS 側 (copy ボタン、3D viewer エラー、Point size スライダ) はこれを `window.__I18N__` 経由で読む |

## 動的レンダリング側で使う dict キー

OVERVIEW / PROBLEM / ENVIRONMENT / USAGE / SAMPLES の中で生成する HTML フラグメントに埋め込むキー一覧:

| 用途 | dict キー |
|---|---|
| 環境カードのラベル | `label_hostname` / `label_os` / `label_cpu` / `label_ram` / `label_gpu` / `label_cuda_driver` / `label_python` |
| 問題設定のラベル | `label_input` / `label_output` |
| 空状態メッセージ | `empty_overview` / `empty_problem` / `empty_environment` / `empty_quickstart` / `empty_advanced` / `empty_developer` / `empty_samples` / `empty_next_actions` |
| Quickstart の Verified バッジ | `verified_badge` |
| Advanced の Source 接頭辞 | `source_label` |
| Sample I/O の figcaption | `fig_input` / `fig_output` / `fig_left` / `fig_right` / `fig_disparity` |
| Sample I/O のメタノート接頭辞 | `note_gaussians` / `note_points` / `note_format` |

## overview ブロックのレンダリング

**`{{OVERVIEW_BLOCK}}`**:

```html
<!-- title が非 null の場合のみ -->
<h3 class="overview-title">{title}</h3>
<!-- tagline が非 null の場合のみ -->
<p class="overview-tagline">{tagline}</p>
<!-- paper_url が非 null の場合のみ -->
<p class="overview-link"><a href="{paper_url}">{paper_url}</a></p>
```

3 フィールド全て `null` の場合: `<p class="usage-empty">{dict.empty_overview}</p>`

## problem ブロックのレンダリング

**`{{PROBLEM_BLOCK}}`** — 各 `summary-item` を順に並べる。label は `dict.label_input` / `dict.label_output`:

| label | value（null は `—`） |
|---|---|
| `dict.label_input` | `{input}` |
| `dict.label_output` | `{output}` |

```html
<div class="summary-grid">
  <div class="summary-item"><label>{dict.label_input}</label><span class="value">{input}</span></div>
  <div class="summary-item"><label>{dict.label_output}</label><span class="value">{output}</span></div>
</div>
```

`input` / `output` 両方 `null` の場合: `<p class="usage-empty">{dict.empty_problem}</p>`

## environment ブロックのレンダリング

**`{{ENVIRONMENT_BLOCK}}`** — 各 `summary-item` を順に並べる。label は dict キー:

| label | value（null は `—`） |
|---|---|
| `dict.label_hostname` | `{hostname}` |
| `dict.label_os` | `{os}` |
| `dict.label_cpu` | `{cpu}` |
| `dict.label_ram` | `{ram_total_gb} GB` |
| `dict.label_gpu + " " + index` | `{name} ({memory_total_mb / 1024:.1f} GB)` — gpus[] 各要素を 1 item ずつ |
| `dict.label_cuda_driver` | `CUDA {cuda_version} / driver {gpus[0].driver_version}` — gpus が空配列なら省略 |
| `dict.label_python` | `{python_version}` |

```html
<div class="summary-grid">
  <div class="summary-item"><label>{label}</label><span class="value">{value}</span></div>
  ...
</div>
```

`environment` 自体が `null` / 空 dict の場合: `<p class="usage-empty">{dict.empty_environment}</p>`

## usage ブロックのレンダリング

**`{{QUICKSTART_BLOCK}}`** — 非 null 時:
```html
<p>{description}</p>
<pre><code>{command}</code></pre>
<p class="usage-note">{verified ? '<span class="usage-verified">' + dict.verified_badge + '</span>' : note}</p>
```
null 時: `<p class="usage-empty">{dict.empty_quickstart}</p>`

**`{{ADVANCED_BLOCK}}`** — 各要素を順に:
```html
<h4>{title}</h4>
<pre><code>{command}</code></pre>
<p class="usage-note">{dict.source_label} {source}{note ? ' — ' + note : ''}</p>
```
空配列時: `<p class="usage-empty">{dict.empty_advanced}</p>`

**`{{DEVELOPER_BLOCK}}`** — 非 null 時:
```html
<p>{description}</p>
<pre><code>{sample_code}</code></pre>
<p class="usage-note">Import: <code>{import_path}</code>{note ? ' — ' + note : ''}</p>
```
null 時: `<p class="usage-empty">{dict.empty_developer}</p>`

## samples ブロックのレンダリング

**`{{SAMPLES_BLOCK}}`** — 各 item を type 別に:

**`image_pair`**:
```html
<div class="sample-item">
  <h4>{label}</h4>
  <div class="sample-grid sample-grid-2">
    <figure><img src="{input_paths[0]}" alt="input" loading="lazy"><figcaption>{dict.fig_input}</figcaption></figure>
    <figure><img src="{output_paths[0]}" alt="output" loading="lazy"><figcaption>{dict.fig_output}</figcaption></figure>
  </div>
</div>
```

**`image_triple`**:
```html
<div class="sample-item">
  <h4>{label}</h4>
  <div class="sample-grid sample-grid-3">
    <figure><img src="{input_paths[0]}" alt="left" loading="lazy"><figcaption>{dict.fig_left}</figcaption></figure>
    <figure><img src="{input_paths[1]}" alt="right" loading="lazy"><figcaption>{dict.fig_right}</figcaption></figure>
    <figure><img src="{output_paths[0]}" alt="disparity" loading="lazy"><figcaption>{dict.fig_disparity}</figcaption></figure>
  </div>
</div>
```

3D type (`gaussian_splat` / `point_cloud` / `mesh`) では **`data-coord-convention="{metadata.coord_convention or 'unknown'}"`** 属性を必ず付ける。viewer 側がこの値を見て X 軸 180° 回転を適用する。値は `opencv` / `opengl` / `z_up` / `unknown` のいずれか。

**`gaussian_splat`**:
```html
<div class="sample-item">
  <h4>{label}</h4>
  <div class="viewer-3d viewer-gsplat" data-src="{output_paths[0]}" data-coord-convention="{metadata.coord_convention}"></div>
  <p class="usage-note">{dict.note_gaussians} {metadata.gaussian_count}</p>
</div>
```
ビューワ本体は template 末尾の `<script type="module">` が Three.js + `@mkkellogg/gaussian-splats-3d` を CDN importmap 経由で動的初期化。GS viewer は既に `cameraUp=[0,-1,0]` で OpenCV 規約に対応済みのため、現状は `data-coord-convention` を読まない（将来的に opengl 入力を扱う際の予約属性）。

**`point_cloud`**:
```html
<div class="sample-item">
  <h4>{label}</h4>
  <div class="viewer-3d viewer-pointcloud" data-src="{output_paths[0]}" data-coord-convention="{metadata.coord_convention}"></div>
  <p class="usage-note">{dict.note_points} {metadata.point_count}</p>
</div>
```
ビューワは Three.js `PLYLoader` + `THREE.Points`。`data-coord-convention="opencv"` で X 軸 180° 回転 (`points.rotateX(π)`)、`"z_up"` で X 軸 -90° 回転。

**`mesh`**:
```html
<div class="sample-item">
  <h4>{label}</h4>
  <div class="viewer-3d viewer-mesh" data-src="{output_paths[0]}" data-coord-convention="{metadata.coord_convention}"></div>
  <p class="usage-note">{dict.note_format} {metadata.format}</p>
</div>
```
ビューワは Three.js `GLTFLoader` / `OBJLoader`。対応: `.glb` / `.gltf` / `.obj`。`data-coord-convention="opencv"` で X 軸 180° 回転を適用。

**`video`**:
```html
<div class="sample-item">
  <h4>{label}</h4>
  <video class="sample-video" src="{output_paths[0]}" autoplay muted loop playsinline preload="metadata">
    Your browser does not support HTML5 video.
  </video>
</div>
```

空配列時: `<p class="usage-empty">{dict.empty_samples}{note ? ' (' + note + ')' : ''}.</p>`

## next_actions ブロックのレンダリング

**`{{NEXT_ACTIONS_BLOCK}}`** — 各要素を順に:

```html
<div class="next-action-item">
  <div class="next-action-header">
    <span class="priority-badge priority-{priority}">{priority}</span>
    <strong>{action}</strong>
  </div>
  <p class="usage-note">{reason}</p>
  <!-- command が非 null の場合のみ -->
  <pre><code>{command}</code></pre>
</div>
```

空配列時: `<p class="usage-empty">{dict.empty_next_actions}</p>`

## HTML エスケープ（共通）

全ブロックでテキスト挿入時は `<`, `>`, `&`, `"`, `'` をエスケープ。属性値は `"` → `&quot;`。
