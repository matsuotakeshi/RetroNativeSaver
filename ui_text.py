"""Dialog language only; never translate stored settings or user content."""
import ctypes
import json
import locale
from pathlib import Path

_language = 'ja'
LANGUAGES = ('auto', 'en', 'ja')
LANGUAGE_LABELS = ('Automatic (Windows) / 自動', 'English', '日本語')


def windows_language():
    """Use the Windows display language, not regional number/date formats."""
    try:
        api = ctypes.WinDLL('kernel32', use_last_error=True).GetUserDefaultUILanguage
        api.argtypes, api.restype = [], ctypes.c_ushort
        language_id = api()
        if language_id:
            return 'ja' if language_id & 0x3ff == 0x11 else 'en'
    except (AttributeError, OSError):
        pass
    try:
        name = locale.getlocale()[0] or ''
    except (ValueError, TypeError):
        name = ''
    return 'ja' if name.lower().startswith(('ja', 'japanese')) else 'en'


def set_language(preference='auto'):
    global _language
    _language = preference if preference in ('ja', 'en') else windows_language()
    return _language


def configure(config):
    return set_language(config.get('ui_language', 'auto') if isinstance(config, dict) else 'auto')


def configure_from_path(path):
    """Read only the language; the caller still reports configuration errors."""
    try:
        config = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        config = {}
    return configure(config)


def language_label(value):
    return dict(zip(LANGUAGES, LANGUAGE_LABELS)).get(str(value), str(value))


def language_value(label):
    return dict(zip(LANGUAGE_LABELS, LANGUAGES)).get(label, label)


def tr(message, **values):
    template = ENGLISH.get(message, message) if _language == 'en' else message
    return template.format(**values) if values else template


ENGLISH = {
    "Language / 言語": "Language / 言語",
    "言語を一覧から選択してください。": "Select a language from the list.",
    "言語の変更は「適用／OK」で保存後、画面を開き直すと反映されます。": "Save the language with Apply / OK, then reopen the window to use it.",
    "RetroNativeSaver {v0} — 設定": "RetroNativeSaver {v0} — Settings",
    "設定は次回のスクリーンセーバー起動から反映されます。": "Settings take effect the next time the screensaver starts.",
    "全般": "General",
    "表示時間は機種別設定が優先されます。ランダム幅・上限 FPS は非同期表示に適用されます。\nRetroArchのEXEはEnterでゲームを開くときに使用します。空欄では従来どおり自動検出します。\nログは初期状態でオフです。オンにすると通常の監視・エラーログを保存します。": "Per-system duration overrides the common duration. Jitter and the FPS limit apply to independent rotation.\nRetroArch opens the selected game when you press Enter. Leave its path blank for automatic detection.\nLogging is off by default. Enable it to save monitoring and error logs.",
    "タイトル表示": "Title Display",
    "1行スクロール時は機種名とタイトルを同じ文字サイズで表示します。色は #RRGGBB で指定します。": "Single-line scrolling uses the same font size for the system and title. Enter colors as #RRGGBB.",
    "グループ表示": "Grouped Display",
    "非同期表示を有効にした全画面起動で抽選します。割合は 50:50 や 15:85 のように指定できます。\n上限 FPS は全般の上限との小さい方です。枠数・負荷上限・グループ構成は既存設定を維持します。": "Selected randomly at full-screen startup with independent rotation enabled. Use ratios such as 50:50 or 15:85.\nThe lower of this FPS limit and the General limit applies. Existing tile counts, resource limits and groups are preserved.",
    "参照…": "Browse…",
    "グループ内で抽選する機種（通常表示には影響しません）": "Systems eligible for grouped display (normal display is unaffected)",
    "管理画面・一覧更新": "Management and Catalog",
    "お気に入り・キー入力…": "Favorites / Input…",
    "ブラック／ホワイトリスト…": "Blacklist / Whitelist…",
    "ROM一覧を更新": "Update ROM Catalog",
    "管理画面は保存済みの設定を使います。管理画面側で保存した変更はキャンセルでは戻りません。": "Management windows use saved settings. Cancel here does not undo changes saved in those windows.",
    "変更した項目だけ保存します。保存時には元のJSONをバックアップします。": "Only edited settings are saved. The original JSON is backed up before saving.",
    "適用": "Apply",
    "キャンセル": "Cancel",
    "ROM一覧を更新中": "Updating ROM Catalog",
    "一覧更新の完了後に設定を保存してください。": "Wait for the catalog update to finish before saving settings.",
    "{v0}ファイルを保存しました。次回起動から反映します。": "Saved {v0} file(s). Changes take effect at the next startup.",
    "変更はありません。": "No changes.",
    " ROM検索条件を変更したため「ROM一覧を更新」を実行してください。": " ROM search settings changed. Run Update ROM Catalog.",
    "\n\n保存済み（バックアップ作成済み）：\n": "\n\nAlready saved (with backups):\n",
    "\n\n残りの変更は未保存です。原因を解消して再度「適用」してください。": "\n\nThe remaining changes are unsaved. Resolve the error, then click Apply again.",
    "保存できなかった変更が残っています。": "Some changes could not be saved.",
    "設定を保存できません": "Unable to Save Settings",
    "一覧更新の完了後に閉じてください。": "Wait for the catalog update to finish before closing.",
    "設定を保存しますか": "Save Settings?",
    "管理画面を開く前に変更を保存しますか？\n「いいえ」は保存済みの設定で開きます。": "Save changes before opening the management window?\nNo opens it using the previously saved settings.",
    "ROM一覧を更新しています…": "Updating the ROM catalog…",
    "管理画面を開けません": "Unable to Open Management Window",
    "処理に失敗しました。設定・フォルダーの指定と書き込み権限を確認してください。": "The operation failed. Check settings, folder paths and write permissions.",
    "処理に失敗しました": "Operation Failed",
    "終了コード: {v0}\n設定・フォルダーの指定と書き込み権限を確認してください。": "Exit code: {v0}\nCheck settings, folder paths and write permissions.",
    "ROM一覧を更新しました。": "ROM catalog updated.",
    "改行・引用符を含まないパス": "a path without line breaks or quotes",
    "改行を含まない文字列": "text without line breaks",
    "#RRGGBB 形式（例: #909090）": "#RRGGBB (for example, #909090)",
    "オンまたはオフ": "on or off",
    "{v0:g}以上": "at least {v0:g}",
    "、{v0:g}以下": " and at most {v0:g}",
    "の整数": " (whole numbers only)",
    "の数値": " (numeric value)",
    "「{v0}」は{v1}を指定してください。": "For {v0}, enter {v1}.",
    "{v0} はJSONオブジェクトにしてください。": "{v0} must be a JSON object.",
    "single_system_mode はJSONオブジェクトにしてください。": "single_system_mode must be a JSON object.",
    "表示の割合は両方を指定し、少なくとも片方を0より大きくしてください。": "Set both display weights, with at least one greater than zero.",
    "設定ファイルの最上位はJSONオブジェクトにしてください。": "The configuration root must be a JSON object.",
    "設定ファイルが別の操作で変更されています。画面を閉じて開き直してください。": "The configuration was changed elsewhere. Close and reopen this window.",
    "保存中に設定ファイルが変更されました。画面を開き直してください。": "The configuration changed while saving. Reopen this window.",
    "「{v0}」の入力を確認してください。": "Check the value for {v0}.",
    "「{v0}」は .zip, .chd のように指定してください。": "For {v0}, enter extensions such as .zip, .chd.",
    "「{v0}」は候補から選択してください。": "Select {v0} from the list.",
    "コアオプション名を確認してください。": "Check the core option name.",
    "core_options はJSONオブジェクトにしてください。": "core_options must be a JSON object.",
    "コアオプション「{v0}」の値を確認してください。": "Check the value for core option {v0}.",
    "{v0} は省略できません。": "{v0} is required.",
    "「{v0}」は空欄にできません。": "{v0} cannot be blank.",
    "「{v0}」を省略する場合は「共通／既定」を選んでください。": "To omit {v0}, select Use common / default.",
    "機種IDがありません。": "The system ID is missing.",
    "読み込みエラー — {v0}": "Read error — {v0}",
    "実行ファイル": "Executable files",
    "libretroコア": "libretro cores",
    "すべてのファイル": "All files",
    "機種別": "Systems",
    "機種：": "System:",
    "機種別設定がありません：{v0}": "No system settings found: {v0}",
    "コアオプション": "Core Options",
    "設定名": "Option name",
    "値": "Value",
    "追加…": "Add…",
    "値を変更…": "Edit Value…",
    "削除": "Remove",
    "このファイルは編集できません。元のJSONは変更しません。\n": "This file cannot be edited. The original JSON will remain unchanged.\n",
    "{v0}\n機種の切り替えでは保存しません。「適用／OK」で編集中の全機種を保存します。": "{v0}\nSwitching systems does not save. Apply / OK saves all edited systems.",
    "機種IDは維持します。共通／既定を選ぶと機種別の指定を外します。セーブ先は一時セーブ領域の設定が優先されます。": "The system ID is preserved. Use common / default removes the system override. Temporary saves take precedence over the save folder.",
    "表示時間は非同期表示で使用します。グループ表示では機種別の同時起動数より既存のグループ用上限が優先されます。": "Duration applies to independent rotation. Grouped display uses its existing group limits instead of per-system instance limits.",
    "ROM検索条件を変更した後は、保存してから「ROM一覧を更新」を実行してください。拡張子が空の場合は全拡張子が対象です。": "After changing ROM search settings, save and run Update ROM Catalog. Blank extensions include all file types.",
    "コア固有の互換性設定です。必要な項目だけ変更してください。ログ用インターフェースとログの保存設定は別の項目です。": "Core-specific compatibility settings: change only what is needed. The core log interface and saving logs are separate settings.",
    "共通／既定を使用": "Use common / default",
    "ダブルクリックで値を変更できます。コアが受け付ける設定名・値を指定してください。変更は「適用／OK」で保存します。": "Double-click to edit. Use option names and values supported by the core. Apply / OK saves changes.",
    "コアオプションを編集できません。未設定の機種を選ぶか、core_options のJSON形式を確認してください。": "Core options cannot be edited. Select another system or check the core_options JSON format.",
    "コアオプションの追加": "Add Core Option",
    "設定名を確認してください": "Check Option Name",
    "空欄・改行は使用できません。": "Blank names and line breaks are not allowed.",
    "登録済みです": "Already Added",
    "一覧から選択して「値を変更」を使ってください。": "Select the option in the list and use Edit Value.",
    "{v0} の値": "Value for {v0}",
    "コアオプションの変更": "Edit Core Option",
    "お気に入り設定の形式が正しくありません。": "Invalid favorites format.",
    "items は一覧で指定してください。": "items must be a list.",
    "各項目には機種IDとROMファイルが必要です。": "Each entry needs a system ID and ROM file.",
    "Retro Native Saver — お気に入り設定": "Retro Native Saver — Favorites",
    "設定を読み込めません": "Unable to Read Settings",
    "毎サイクル、お気に入りからランダムに1本を必ず選ぶ": "Always select one random favorite each cycle",
    "先頭の1枠に表示します。残りの枠は通常のランダム表示です。": "The favorite appears in the first tile. Other tiles use normal random selection.",
    "機種": "System",
    "タイトル": "Title",
    "自動入力": "Startup input",
    "ROMファイル": "ROM file",
    "自動入力の設定を確認してください": "Check Startup Input Settings",
    "お気に入りにするROMを選択（複数選択可）": "Select ROMs to add to favorites (multiple selection allowed)",
    "項目を選択してください": "Select an Entry",
    "自動入力を変更するお気に入りを選択してください。": "Select the favorite whose startup input you want to change.",
    "保存できません": "Unable to Save",
    "保存しました": "Saved",
    "次の表示サイクルから反映されます。": "Changes take effect from the next display cycle.",
    "変更の保存": "Save Changes",
    "変更を保存して閉じますか？": "Save changes before closing?",
    "ROMを追加…": "Add ROMs…",
    "自動入力を適用": "Apply Startup Input",
    "選択した項目を削除": "Remove Selected",
    "閉じる": "Close",
    "保存": "Save",
    "お気に入り枠ではブラックリストを無視します。負荷上限・起動条件・実行中の障害隔離は維持します。\n全件利用できない場合は通常表示を続け、理由をログに記録します。": "The favorite tile ignores the blacklist. Resource limits, startup requirements and session fault isolation still apply.\nIf no favorites are available, normal selection continues; the reason is logged when logging is enabled.",
    "連続入力には1つ以上の入力を指定してください。": "An input sequence needs at least one step.",
    "入力は開始からの秒数が小さい順に並べてください。": "Arrange input steps in ascending order of time from startup.",
    "自動入力は秒数・入力種類・キーを指定してください。": "Startup input requires a delay, input type and key.",
    "入力までの秒数は0以上の有限の数値にしてください。": "The input delay must be a finite number of zero or greater.",
    "入力種類とキーを一覧から選択してください。": "Select the input type and key from the lists.",
    "設定なし": "None",
    "ボタン": "Button",
    "キー": "Key",
    "{v0:g}秒後 / {v1}: {v2}": "After {v0:g}s / {v1}: {v2}",
    "このROMの自動入力": "Startup Input for This ROM",
    "ゲームボタン": "Game button",
    "有効": "Enabled",
    "開始からの秒数を小さい順に設定します。例：5秒 Start → 6秒 A → 8秒 Enter": "Use ascending times from startup. Example: 5s Start → 6s A → 8s Enter",
    "開始からの秒数": "Seconds from startup",
    "入力種類": "Input type",
    "選択した入力：開始から": "Selected step: after",
    "秒後に": "seconds,",
    "キーボード": "Keyboard",
    "を1回押す": "press once",
    "入力を追加": "Add Step",
    "入力を削除": "Remove Step",
    "追加時は最後の入力を1秒後に繰り返します。各行で変更できます。": "Adds the last input again, 1 second later. Edit each row as needed.",
    "追加するROMに適用します。登録済みの項目は選択して「自動入力を適用」→「保存」を押してください。": "Applies to newly added ROMs. For existing favorites, select entries, click Apply Startup Input, then Save.",
    "通常枠でも有効です。既定の自動Start入力より優先します。同時刻は1つずつ押して離します。": "Also applies in normal tiles and overrides automatic Start. Inputs at the same time are pressed and released in order.",
    "入力までの秒数を数値で入力してください。": "Enter a number for the input delay.",
    "{v0:g}秒": "{v0:g}s",
    "入力の設定を確認してください": "Check Input Settings",
    "ROMフォルダーが見つかりません: {v0}": "ROM folder not found: {v0}",
    "ROMを読み込めません": "Unable to Read ROMs",
    "お気に入りに追加 — {v0}": "Add to Favorites — {v0}",
    "タイトル・ファイル名で検索（複数選択可）": "Search by title or file name (multiple selection allowed)",
    "{v0} / {v1} 件（検索前に選択した項目も保持します）": "{v0} / {v1} entries (selections are kept when searching)",
    "選択したROMを追加": "Add Selected ROMs",
    "{v0}: systems の形式が正しくありません。保存せず終了します。": "{v0}: invalid systems format. Exiting without saving.",
    "{v0}: 機種別一覧の形式が正しくありません。": "{v0}: invalid per-system list format.",
    "{v0}: ROM名の形式が正しくありません。": "{v0}: invalid ROM name format.",
    "{v0}: 障害記録の形式が正しくありません。": "{v0}: invalid failure record format.",
    "手動登録": "Added manually",
    "機種名とROM名が必要です。": "A system name and ROM name are required.",
    "保存中に別の変更を検出しました。「再読み込み」してやり直してください。": "Another change was detected while saving. Click Reload and try again.",
    "Retro Native Saver — ブラックリストからホワイトリストへ": "Retro Native Saver — Blacklist / Whitelist",
    "再表示したいROMを選択し、ホワイトリストへ登録してください。Ctrl / Shiftで複数選択できます。": "Select ROMs to allow again and add them to the whitelist. Use Ctrl / Shift for multiple selection.",
    "変更は次回のセーバー起動から反映します。登録後も、実行中に異常が出たROMはその回だけ除外されます。": "Changes apply at the next saver startup. A ROM that fails during a session is still excluded for that session.",
    "注意：config.jsonでホワイトリストが無効です。有効にするまで登録内容は適用されません。": "Note: the whitelist is disabled in config.json. Entries take effect only after it is enabled.",
    "検索：": "Search:",
    "除外前の失敗記録も表示": "Include failures below the blacklist threshold",
    "状態": "Status",
    "失敗回数": "Failures",
    "直近の理由": "Last reason",
    "最終失敗（UTC）": "Last failure (UTC)",
    "登録済み（許可）": "Whitelisted",
    "ブラックリスト": "Blacklisted",
    "失敗記録のみ": "Failure history only",
    "表示 {v0} 件 / 障害記録 {v1} 件": "Showing {v0} / {v1} failure records",
    "読み込みに失敗しました。ファイルを確認して再読み込みしてください。": "Unable to read the list. Check the files and click Reload.",
    "読み込みエラー": "Read Error",
    "保存できませんでした": "Unable to Save",
    "{v0} 件を登録しました。次回起動から反映します。": "Added {v0} entry/entries. Changes apply at the next startup.",
    "登録完了": "Entries Added",
    "{v0} 件をホワイトリストに登録しました。\nブラックリストの履歴は保持しています。": "Added {v0} entry/entries to the whitelist.\nBlacklist history has been preserved.",
    "\n\nバックアップ：\n{v0}": "\n\nBackup:\n{v0}",
    "選択したROMをホワイトリストへ登録": "Add Selected ROMs to Whitelist",
    "再読み込み": "Reload",
    "保存先：{v0}": "Save location: {v0}",
    "設定画面を開けませんでした。\n{v0}\n\n既存の設定ファイルは変更していません。": "Unable to open settings.\n{v0}\n\nThe existing configuration has not been changed.",
    "ROMリスト画面を開けませんでした。\n{v0}": "Unable to open the ROM list editor.\n{v0}",
    "お気に入り設定画面を開けませんでした。\nPythonのTcl/Tkを含めてビルドし直してください。\nfavorites.json を直接編集することもできます。\n\n{v0}": "Unable to open favorites.\nRebuild with Python Tcl/Tk included.\nYou can also edit favorites.json directly.\n\n{v0}",
    "RetroArchを起動できませんでした。\n{v0}": "Unable to launch RetroArch.\n{v0}",
    "RetroArchのEXE（空欄で自動検出）": "RetroArch EXE (blank: auto-detect)",
    "複数モニターに表示する": "Use multiple monitors",
    "枠ごとに非同期で入れ替える": "Rotate each tile independently",
    "共通の表示時間（秒）": "Common duration (seconds)",
    "表示時間のランダム幅（±秒）": "Duration jitter (± seconds)",
    "非同期表示の上限 FPS": "Independent rotation FPS limit",
    "通常表示の枠数上限／モニター": "Normal display tile limit per monitor",
    "フェードする": "Enable fades",
    "フェード時間（ミリ秒）": "Fade duration (milliseconds)",
    "マウスで終了する移動量（px）": "Mouse movement to exit (pixels)",
    "矢印・Insert・Delete・Enter操作を使う": "Enable arrow / Insert / Delete / Enter controls",
    "ログを出力する": "Write logs",
    "機種名・タイトルを表示する": "Show system and game titles",
    "1行でスクロールする": "Scroll on one line",
    "機種名／スクロールの文字サイズ（px）": "System / scrolling font size (pixels)",
    "固定表示のタイトル文字サイズ（px）": "Static game title font size (pixels)",
    "スクロール速度（px／秒、0で停止）": "Scroll speed (pixels/s; 0: stopped)",
    "スクロール前の待ち時間（秒）": "Pause before scrolling (seconds)",
    "繰り返しの間隔（px）": "Repeat gap (pixels)",
    "機種名の色": "System name color",
    "タイトルの色": "Game title color",
    "背景の濃さ（0:透明、255:黒）": "Background opacity (0: clear, 255: black)",
    "画面端からの余白（px）": "Edge margin (pixels)",
    "文字まわりの余白（px）": "Text padding (pixels)",
    "グループ表示を抽選に含める": "Include grouped display in random selection",
    "通常表示の割合": "Normal display weight",
    "グループ表示の割合": "Grouped display weight",
    "グループ表示の上限 FPS": "Grouped display FPS limit",
    "この機種を使用する": "Enable this system",
    "表示名": "Display name",
    "libretroコア（DLL）": "libretro core (DLL)",
    "ROMフォルダー": "ROM folder",
    "BIOSフォルダー": "BIOS folder",
    "セーブフォルダー": "Save folder",
    "アセットフォルダー": "Assets folder",
    "一時セーブ領域を使う（終了時に破棄）": "Use temporary saves (discard on exit)",
    "表示時間（秒）": "Duration (seconds)",
    "通常表示の同時起動数（0で起動なし）": "Normal display instances (0: disabled)",
    "負荷グループ（空欄で制限対象外）": "Resource group (blank: unrestricted)",
    "1枠あたりの負荷（weight）": "Resource weight per tile",
    "描画方式": "Renderer",
    "OpenGL描画領域の幅": "OpenGL context width",
    "OpenGL描画領域の高さ": "OpenGL context height",
    "ROM拡張子（カンマ区切り）": "ROM extensions (comma-separated)",
    "展開後の拡張子（カンマ区切り）": "Extracted extensions (comma-separated)",
    "サブフォルダーも検索する": "Search subfolders",
    "アーカイブの扱い": "Archive handling",
    "一覧作成時にアーカイブ内容を検査する": "Validate archive contents when building catalog",
    "ファイル名で除外する文字列（1行に1件）": "Exclude file names containing (one per line)",
    "複数ディスクの起動方式": "Multi-disk boot mode",
    "起動後にStartを2回送る": "Send Start twice after startup",
    "MAMEの機種名（autoで自動）": "MAME system name (auto: detect)",
    "MAMEのBIOS ZIPフォルダー": "MAME BIOS ZIP folder",
    "周期終了時にプロセスを作り直す": "Restart process at the end of each cycle",
    "コアへログ用インターフェースを提供する": "Provide core logging interface",
    "コアへ性能情報インターフェースを提供する": "Provide core performance interface",
    "毎フレーム描画コンテキストを再設定する": "Rebind rendering context every frame",
    "タイトル一覧にあるROMだけを使う": "Use only ROMs found in the title database",
    "タイトル情報ファイル": "Title metadata file",
    "タイトル情報の参照元（1行に1件）": "Title metadata sources (one per line)",
    "タイトル照合用コア名（1行に1件）": "Core names for title matching (one per line)",
    "タイトル照合用ROMルート（1行に1件）": "ROM roots for title matching (one per line)",
    "表示・負荷": "Display / Load",
    "ROM・起動": "ROM / Startup",
    "基本": "Basic",
    "詳細": "Advanced"
}
