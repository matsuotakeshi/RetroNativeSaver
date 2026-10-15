# RetroNativeSaver

Windows向けの、複数のゲーム映像をタイル表示するスクリーンセーバーです。libretroコアを各タイルの独立した子プロセスで実行します。現在の版は **v0.21.19** です。

本体は **GNU GPL v3（GPL-3.0-only）** で公開しています。X1/libretroなどの第三者コードには、[個別のライセンス](THIRD_PARTY_NOTICES.md)が適用されます。

## 主な機能

- 複数モニターへの表示、タイルごとのROM抽選・フェード・周期変更。
- 左上のお気に入り枠、お気に入りごとの連続したボタン・キーボード入力。
- resource_group / resource_weightによる同時実行の負荷制限。
- ブラックリスト・ホワイトリストの管理、失敗したROMの再試行。
- 通常表示とグループ表示の起動時抽選。グループ表示は1920×1080に28枠、2560×1080に36枠。FBNeo単独グループは16＋16枠。
- PC88・PC98・X1・X68000などの複数ディスク準備。対応機種一覧とコアの設定例は`systems.example/`を参照してください。

## 必要なもの

Windows x64、Python、PyInstaller、および各機種のlibretroコア・ROM・必要なBIOSを用意してください。開発環境ではPython 3.14でテストしています。ROM・BIOS・個人のセーブ・お気に入り・ROM一覧はこのリポジトリに含みません。

## 初期設定とビルド

```powershell
python -m pip install -r requirements.txt
python initialize_config.py
```

初期化で`config.json`、`favorites.json`、`systems/`と空のホワイトリストを作成します。既存ファイルは上書きしません。サンプルの`C:/ROMs/<機種ID>`、`C:/RetroArch-win64/cores`、BIOSのパスを、ご自身の環境に合わせて編集してください。使用しない機種は`enabled`を`false`にしてください。

```powershell
.\build.bat
```

`dist/RetroNativeSaver/`に実行ファイル・SCR・必要な補助ファイルを作成します。配布先ではフォルダー全体を保持してください。ビルド時にも初期設定の不足分だけを作成します。

1. `dist/RetroNativeSaver/update_rom_catalog.bat`を実行して、固定ROM一覧を作成します。
2. `test_saver.bat`で表示を確認します。
3. `install_saver.bat`で登録し、Windowsのスクリーンセーバー設定を確認します。

ROMを追加・移動したら`update_rom_catalog.bat`で一覧を手動更新してください。既存の運用環境を更新する場合は、そちらの設定・save・state・お気に入りを保持してください。

X1の2ドライブ対応コアは専用ビルドです。DLLはGitに含めていません。[ビルド手順](cores/X1_BUILD.md)に従い、`cores/x1_rns_libretro.dll`を用意してください。その他のコアは外部のlibretroコアを使用します。

## 起動中の操作

| 操作 | 動作 |
|---|---|
| 左・右 | タイルを選択。操作が途切れると選択表示が消えます |
| Insert | 選択したゲームをお気に入りへ追加 |
| Delete | 通常枠ならブラックリストへ追加。お気に入り枠ならお気に入りから削除。その枠を入れ替え |
| 上 | 全枠のROMを入れ替え |
| 下 | お気に入り枠だけ入れ替え |
| Enter | 選択したゲームをRetroArchへ引き継いで終了 |
| マウス・タッチ・その他の終了用キー | スクリーンセーバーを終了 |

`configure_favorites.bat`でお気に入りと起動後の入力を編集できます。`configure_rom_lists.bat`でROMリストを管理できます。

## グループ表示

初期設定は通常表示50%／グループ表示50%です。`single_system_mode.normal_weight`と`grouped_weight`の比で変更できます。グループは起動ごとに1つ選び、その回は選ばれたグループ内でROMを入れ替えます。

```json
[
  ["megadrive", "megacd"],
  ["pcengine", "pcenginecd"],
  ["gb", "gbc", "gba"],
  ["fds", "nes"],
  ["snes"],
  ["fbneo"],
  ["msx", "x1", "x68000", "pc88", "pc98"],
  ["neocd"]
]
```

`single_system_mode.disabled_systems`の機種はグループ表示から除外します。サンプルでは`["fbneo"]`でFBNeoを停止しています。`[]`で再開できます。通常表示の機種設定には影響しません。表示上限は25fpsですが、必要な負荷・メモリーは機種とROMによって変わります。

## 開発・テスト

```powershell
python initialize_config.py
python -m unittest discover -v
```

Windows向けの回帰テストを含みます。比較用の旧コードは`tests_fixtures/`に限定しています。v0.21.19はこの公開用構成でも652テストが成功しています。全機種・全ROM・すべてのPCでの長時間動作を保証するものではありません。

[資源の所有と終了処理](docs/OWNERSHIP_NOTES.md)に、プロセス・コア・描画資源・設定の責務を記載しています。

## リポジトリと個人データ

実行用の設定・お気に入り・ROM一覧・ログ・save・生成されたタイトル情報は`.gitignore`で除外しています。配布用の設定例は`config.example.json`と`systems.example/`です。元の配布フォルダーにあった個別環境の調査記録は含めていません。

## ライセンス

RetroNativeSaver独自のソースコード・テスト・スクリプト・ドキュメント・設定例などは、別途記載のあるものを除き **GNU General Public License version 3のみ（SPDX: `GPL-3.0-only`）** で提供します。著作権表示と適用範囲は [COPYRIGHT](COPYRIGHT)、ライセンス全文は [LICENSE](LICENSE) を参照してください。ライセンス全文は[GNUの公式本文](https://www.gnu.org/licenses/gpl-3.0.txt)を変更せず収録しています。

本ソフトウェアは無保証です。再配布・改変はGPL v3の条件に従って行えます。

X1の`xmil-libretro`ソースおよび専用変更は、上流のライセンス体系を維持します。ルートLICENSEはBSD 3-Clause、一部libretroヘッダーはMITです。各著作権・許諾・免責表示を保持し、[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)と [third_party/licenses/](third_party/licenses/) に対象と原文をまとめています。外部コアもそれぞれのライセンスに従います。

ビルド時には本体のライセンス文書と第三者コードの文書・ソースアーカイブも配布フォルダーへコピーします。実行ファイルを公開する際は、それに対応する本体のソースとビルド手順も提供してください。
