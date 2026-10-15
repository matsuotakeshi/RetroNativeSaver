# 資源の所有・状態と設定の更新時機（v0.20.111）

## プロセスの所有

| 所有者 | 資源 | 正常時の終了 | 失敗時 |
|---|---|---|---|
| 親supervisor | worker Job | 最終CloseHandleで所属プロセスを終了 | 戻り値を確認。失敗したハンドルを保持し、親のプロセス終了へ引継ぎ |
| 親supervisor | Job割当前のworker | 割当後にJobへ管理を引継ぎ | 割当前の例外では個別kill/waitも試みる |
| 親supervisor | backdrop/guard/shared trace/config snapshot | Job→デスクトップ復旧→guard→trace→snapshot | 独立した各処理を継続。失敗した所有者を保持し、entryで強制終了 |
| scheduler | タイルJob、一時フォルダー、各タイルrecord | Job close後、各タイルをdispose、最後にtemp.cleanup | 1本の失敗でも他を回収。未回収recordがあればフォルダーを保持 |
| 各タイルrecord | proc/trace/content_dir | 終了確認→trace閉鎖→作業ファイル削除 | kill失敗でもwaitを試す。終了を確認できなければtrace・ファイルを保持 |
| 起動準備中のscheduler | Popen前のtrace | recordへ引継ぎ | spec/title書込やPopenの失敗でもtraceを閉じる |

Job作成は、ハンドル取得直後からtry/finallyで保護し、設定が完了して呼出し元へ渡すまで作成側が所有する。shared traceの初期書込に失敗した場合も、参照を捨てる前に閉じる。

process_cleanup.pyの保持リストは、通常の再利用キャッシュではない。失敗資源の参照を切らずにプロセス終了へ到達するための最後の保険。子が生きている可能性がある場合、TemporaryDirectoryの終了時削除も解除する。該当異常時は一時フォルダーが残る場合がある。確認せずに削除しないことを優先する。

正常な親終了に新しいworker待機は追加していない。個別kill/waitはJob割当前の例外経路のみ追加。既存の監視時間・5秒wait・Job/gate順序・通常終了順は維持する。OSやドライバー内で終了できない障害までPythonから回収を保証するものではない。

## コアの状態

| 状態・属性 | 意味 | closeの扱い |
|---|---|---|
| dllあり、_initialized=False | DLL確保、初期化未完了 | 未初期化ならretro_deinitしない |
| _initialized=True、_game_loaded=False | retro_init成功、ゲーム未ロード | deinit→WGL解放→FreeLibrary |
| _game_loaded=True | ROMロード済み | 必要なcontext_destroyとunload→deinit→WGL→FreeLibrary |
| _cleanup_uncertain=True | callback/native lifecycleの失敗で状態不確定 | DLLを再度呼ばず保持しプロセス終了 |
| _cleanup_requires_recycle=Trueのみ | WGL/FreeLibrary等の回収未完了 | 完了済みのnative処理を繰り返さず残りだけ再試行可能。ただし次のコア開始は禁止 |
| dll/contextともなし | OS資源解放済み | 二重解放しない |

_retain_for_recycleが「保持」「終了必要」「不確定」をまとめて更新する。初期化側・callback側はretain_uncertain経由、通常の解放失敗側はclose_core経由。_cleanup_uncertainは失敗後に勝手に解除しない。

Dolphin等のdestroy_hw_before_unload、WGL共有コンテキストの順番、callbackの参照保持、ネイティブDLL内部の動作は変更しない。上表はホストが追跡できる状態の説明であり、コア内部資源の所有を移し替えたものではない。

## 設定の出所と更新

| データ | 読む場所・時機 | 互換性として残す点 |
|---|---|---|
| config.json | 親の起動時。workerへ共有snapshotで引継ぎ | workerで別時点のファイルへ勝手に切り替えない。不正snapshotのfile fallbackなし |
| systems/*.json | workerの準備時。read_system_configで1ファイルを読む | 読込・JSON/構造操作エラーは従来どおりログを出して当該ファイルをスキップ。キー検証の全面厳格化なし |
| slot spec | schedulerが選択した時点にsystem/cfg等を書き、子が読む | 実行中の編集を子の起動途中に混ぜない。Job所属後gateで開始 |
| ブラック/ホワイトリスト | 親session準備、scheduler安全フィルター | 白による救済とsession隔離の役割を維持 |
| favorites.json | schedulerの更新検知、通常モードのサイクル更新 | 起動時固定へ変更しない |
| state/rom_catalog.json | workerの起動時 | 手動更新方式、signature不一致時の機種別走査、安全フィルターを維持 |

固定一覧更新コマンドは、壊れたsystemsで良好な一覧を置き換えないため通常workerより厳格。これはv109からの既存仕様であり、今回読込関数の共通化を理由に同一化しない。

## resourceの互換境界

v113でユーザー指定により通常モード基準へ統一。resource_weightは省略/変換失敗時1・負数0。group名はstr化してstripし、空文字ならグループなし。resource_groups/グループ定義が非dict、max_weight変換失敗・省略・0以下は上限なし。明示的nullは通常と同じ"None"グループになる。独立の使用量・候補可否・お気に入り予約も通常の共通関数を使う。max_concurrentの不正値の例外と、役割別の省略時既定値は維持する。heavy_cd専用リストはない。

起動中のタイルもresource予約に含め、2並列の上限とresource上限の両方を満たす場合だけ新たに起動する。

## 残す境界

main/supervisor_mainには画面・ループ・安全状態の組合せがまだ残る。今回、親セッション終了と所有権移譲を明示したが、状態付きcallbackを丸ごと別クラスへ移動していない。さらに整理する場合も、終了順と特殊コア処理を固定した小単位に分ける。

お気に入り照合は固定一覧により約0.2秒になった実測があるため、非同期スレッド・世代管理は今回は導入しない。将来大規模化で再び応答性が問題になった場合に検討する。


## v112: 親の状態の寿命

| 所有者 | 寿命 | 内容 | 終了処理 |
|---|---|---|---|
| SupervisorSafety | 親のセッション | 永続ROM履歴、whitelist、隔離、障害回数、機種一時停止 | Python管理の状態のみ。worker再起動時は保持 |
| WorkerWatchdog | 1 worker | 監視時刻・進捗key・停止snapshot | 新workerで新規作成。プロセス/traceは所有しない |
| supervisor_main | 親のセッション | Job、backdrop、guard、trace、config snapshot、worker | 既存process_cleanupへ引継ぎ |

SupervisorSafety.loadはworker起動前に一度呼び出す。故障履歴更新は従来の順序と部分更新を保持し、save失敗時に推測で巻き戻さない。監視用閾値の初期読込・ログも既存のタイミングのまま保持する。WorkerWatchdogは共有mappingを借りて読むだけで、破棄・閉鎖しない。監視の停止時に保持したsnapshotはworker退出後の既存判定に使用する。
