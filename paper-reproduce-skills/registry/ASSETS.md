# 手動 provisioning 資産レジストリ (Manual-Asset Registry)

一部の CV 論文は、**ライセンス登録に同意しないと取得できない**モデルに依存します。代表例が Max Planck Institute（Michael Black ラボ）製の **SMPL / SMPL-X / SMPL+H / MANO / FLAME / STAR / SMAL**。これらは HuggingFace のようなトークン自動 DL も GitHub からの自動取得もできません。

このレジストリは、それらを **ユーザーが一度だけ手作業で用意** し、以後 `paper-reproducer` が自動で各リポジトリの期待パスへ配置するための置き場です。

> **paper-reproducer はこれらの資産をダウンロード・同梱・ミラー・再配布しません。** 取得と利用は各モデルのライセンス（**非商用の学術研究目的**）に従い、利用者の責任で遵守してください。

## 仕組み

```
（初回のみ）各サイトでライセンス登録 → モデルを DL → 下記レイアウトで配置
（毎回）  ./bootstrap.sh <repo>  →  /reimplement
          → repo が必要とするモデルを検出し、レジストリから期待パスへ自動コピー
          → 配置物は .gitignore 済み（git / 成功アーカイブには絶対に入らない）
```

- 置き場所: 既定は **プロジェクト内の `manual-assets/`**（`paper-reproducer` リポジトリ直下、`.gitignore` 済み）。環境変数 **`MANUAL_ASSETS_DIR`** で別パスに変更可。
- 第三者の非商用研究ライセンス資産なので **git にはコミットされません**（`manual-assets/` を `.gitignore` 済み）。
- コンテナには `:ro`（読み取り専用）で `/manual-assets` にマウントされます。
- 状態確認: `./bootstrap.sh --list-assets`

## 正規レイアウト

MPI モデル群は `smplx` PyPI パッケージの慣習（`<model_type>/<FILE>`）に揃えます。多くのリポジトリがこの構造を期待するため、自動配置のマッピングが最小化されます。

```
$MANUAL_ASSETS_DIR/
├── smpl/   SMPL_NEUTRAL.pkl  SMPL_MALE.pkl  SMPL_FEMALE.pkl   # 旧命名 basicModel_*_lbs_10_207_0_v1.0.0.pkl も可
├── smplx/  SMPLX_NEUTRAL.npz  SMPLX_MALE.npz  SMPLX_FEMALE.npz
├── smplh/  SMPLH_NEUTRAL.npz  SMPLH_MALE.pkl  SMPLH_FEMALE.pkl
├── mano/   MANO_LEFT.pkl  MANO_RIGHT.pkl
├── flame/  generic_model.pkl  female_model.pkl  male_model.pkl   # FLAME2020/ 一式
├── star/   neutral.npz  male.npz  female.npz
└── smal/   smal_CVPR2017.pkl  smal_CVPR2017_data.pkl  symIdx.pkl
```

> 必要なモデルだけ（依存する論文に応じて）置けば十分です。全種揃える必要はありません。gender のサブセットだけでも、その範囲で自動配置されます。

## 取得元・ライセンス

| モデル | 種別 | 取得元 | ライセンス |
|---|---|---|---|
| SMPL | 人体 | https://smpl.is.tue.mpg.de/ | 非商用研究のみ |
| SMPL-X | 人体+手+顔 | https://smpl-x.is.tue.mpg.de/ | 非商用研究のみ |
| SMPL+H | 人体+手 | https://mano.is.tue.mpg.de/ | 非商用研究のみ |
| MANO | 手 | https://mano.is.tue.mpg.de/ | 非商用研究のみ |
| FLAME | 頭・顔 | https://flame.is.tue.mpg.de/ | 非商用研究のみ |
| STAR | 人体（SMPL 後継） | https://star.is.tue.mpg.de/ | 非商用研究のみ |
| SMAL | 四足動物 | https://smal.is.tue.mpg.de/ | 非商用研究のみ |

各サイトでアカウント登録 → ライセンス同意 → ダウンロード、の手順です。機械可読な索引は同ディレクトリの `manifest.json`。

## ライセンス・商用境界（重要）

- これらは **非商用の学術研究目的** ライセンスです。商用案件での利用可否は各ライセンス本文を確認し、必要なら権利元へ商用ライセンスを問い合わせてください。
- `paper-reproducer` が生成する成功アーカイブ（`{repo}-{sha}.tar.gz`）や git コミットに、配置したモデル実体は **含まれません**（`.gitignore` + `git archive HEAD` の tracked-only 収録で保証）。再配布を避けるためです。

## 将来の拡張

MPI 以外でもライセンス登録・手作業 DL が必須な資産（BFM、EULA データセット等）は、`manifest.json` の `assets[]` に同じ形式で追記すれば本機構で扱えます。
