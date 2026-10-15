# Third-party notices / 第三者コードのライセンス

RetroNativeSaver独自部分のライセンスは **GPL-3.0-only** です（[LICENSE](LICENSE)、[COPYRIGHT](COPYRIGHT)）。以下の第三者コードには、それぞれのライセンスと著作権表示が適用されます。本体のGPL v3宣言によって、これらの表示を置き換えません。

## X1 / xmil-libretro

| 項目 | 内容 |
|---|---|
| 上流 | [libretro/xmil-libretro](https://github.com/libretro/xmil-libretro) |
| 元コミット | [`3106aa54ffb244cca4019a6e95dacaa698781bc3`](https://github.com/libretro/xmil-libretro/tree/3106aa54ffb244cca4019a6e95dacaa698781bc3) |
| 同梱ソース | [third_party/xmil-two-drive-source.zip](third_party/xmil-two-drive-source.zip) |
| 上流のルートLICENSE | BSD 3-Clause。`Copyright © 2015年 Yui`。ファイル内に別の表示がある部分は、その表示も参照してください |
| 原文 | [cores/X1_LICENSE.txt](cores/X1_LICENSE.txt)、[第三者ライセンス用のコピー](third_party/licenses/xmil-libretro-BSD-3-Clause.txt)、ZIP内の`LICENSE` |
| 変更内容 | M3Uの1～2ディスクを読み取り、2枚目をドライブ2へ挿入する専用ビルド。詳細は[ビルド手順](cores/X1_BUILD.md) |

X1の専用変更を含むソースアーカイブは、上流のライセンス体系を維持します。GPL v3へ一括変更したものではありません。既存の著作権・ライセンス・免責条項と各ファイルの表示は保持しています。

Gitリポジトリにはビルド済みX1 DLLを含みません。X1 DLLを配布する場合も、元のライセンスが要求する著作権表示・条件・免責条項を添付してください。

## X1アーカイブ内のlibretroヘッダー

次のヘッダーには、個別に **MIT License** の許諾文が記載されています。上記のBSD 3-Clauseだけでアーカイブ全体のライセンスを表すことはできません。

| アーカイブ内のファイル | 元の著作権表示 |
|---|---|
| `libretro/libretro.h` | 2010–2020 The RetroArch team |
| `libretro/include/features_cpu.h` | 2010–2017 The RetroArch team |
| `libretro/include/retro_common_api.h` | 2010–2016 The RetroArch team |
| `libretro/include/retro_endianness.h` | 2010–2020 The RetroArch team |
| `libretro/include/retro_inline.h` | 2010–2020 The RetroArch team |

元ファイルの許諾文はアーカイブ内にそのまま残しています。確認・配布用に、各ヘッダーの冒頭の著作権・ライセンス表示を [xmil-libretro-MIT-notices.txt](third_party/licenses/xmil-libretro-MIT-notices.txt) にも抜粋しています。その他のファイルについても、アーカイブ内の個別表示を保持してください。

## 外部コアと実行環境

各libretroコア、RetroArch、Python、PyInstallerおよびその他の外部依存物には、それぞれのライセンスが適用されます。設定例に機種やDLL名を記載していても、本プロジェクトがそれらをGPL v3で再許諾することにはなりません。外部コア・ROM・BIOSは、このGitリポジトリに同梱していません。

## 配布時のファイル

`build.bat`は、`LICENSE`、`COPYRIGHT`、この文書、`third_party/`を配布フォルダーへコピーします。X1側の文書は既存の`cores/`とともにコピーします。これにより、X1ソースアーカイブと個別ライセンスも配布先に残ります。

実行ファイルを公開する場合は、その実行ファイルに対応するRetroNativeSaverのソースとビルド手順もGPL v3に従って提供してください。文書の同梱だけで、対応ソースの提供を代替するものではありません。
