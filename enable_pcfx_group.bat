@echo off
setlocal
set "RNS_PCFX_GROUP_BATCH=%~f0"
set "RNS_PCFX_GROUP_CONFIG=%~1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$body = ([IO.File]::ReadAllText($env:RNS_PCFX_GROUP_BATCH) -split '(?m)^# RNS_POWERSHELL_START\r?$', 2)[1]; & ([scriptblock]::Create($body))"
set "RNS_PCFX_GROUP_RESULT=%ERRORLEVEL%"
if defined RNS_PCFX_GROUP_CONFIG exit /b %RNS_PCFX_GROUP_RESULT%
echo.
pause
exit /b %RNS_PCFX_GROUP_RESULT%
# RNS_POWERSHELL_START
$ErrorActionPreference = 'Stop'
$temporaryPath = $null
try {
    $configPath = $env:RNS_PCFX_GROUP_CONFIG
    if (!$configPath) { $configPath = Join-Path (Split-Path -Parent $env:RNS_PCFX_GROUP_BATCH) 'config.json' }
    $configPath = [IO.Path]::GetFullPath($configPath)
    if (!(Test-Path -LiteralPath $configPath -PathType Leaf)) {
        throw 'config.jsonが見つかりません。v0.21.23以降の更新ファイルと、このバッチを既存の設置先へコピーしてから実行してください。'
    }
    $originalBytes = [IO.File]::ReadAllBytes($configPath)
    $originalText = Get-Content -LiteralPath $configPath -Encoding UTF8 -Raw
    $config = $originalText | ConvertFrom-Json
    $groups = $config.single_system_mode.groups
    if ($groups -isnot [Array]) { throw 'single_system_mode.groupsがありません。グループ構成を確認してください。' }
    $matches = @(for ($index = 0; $index -lt $groups.Count; $index++) {
        $group = $groups[$index]
        if ($group -is [Array] -and $group -contains 'pcengine' -and
            ($group -contains 'pcenginecd' -or $group -contains 'cdrom2')) { $index }
    })
    if ($matches.Count -ne 1) { throw 'PC Engine / CD-ROM2のグループを一つに特定できませんでした。設定は変更していません。' }
    $index = $matches[0]
    if ($groups[$index] -contains 'pcfx') { Write-Host 'PC-FXはこのグループに追加済みです。変更はありません。'; exit 0 }
    $oldGroup = $groups[$index]
    $before = $config | ConvertTo-Json -Depth 100 -Compress
    $groups[$index] = @($oldGroup) + @('pcfx')
    $updatedText = $config | ConvertTo-Json -Depth 100
    $check = $updatedText | ConvertFrom-Json
    if ($check.single_system_mode.groups[$index][-1] -ne 'pcfx') { throw '更新内容の検証に失敗しました。' }
    $check.single_system_mode.groups[$index] = $oldGroup
    if (($check | ConvertTo-Json -Depth 100 -Compress) -cne $before) { throw '対象グループ以外の値に差があるため中止しました。' }
    $suffix = (Get-Date -Format 'yyyyMMdd_HHmmss') + '_' + [Guid]::NewGuid().ToString('N').Substring(0, 8)
    $backup = $configPath + '.before-pcfx-group.' + $suffix + '.bak'
    $temporaryPath = $configPath + '.' + $suffix + '.tmp'
    [IO.File]::WriteAllText($temporaryPath, $updatedText + "`r`n", [Text.UTF8Encoding]::new($false))
    if ([Convert]::ToBase64String([IO.File]::ReadAllBytes($configPath)) -cne [Convert]::ToBase64String($originalBytes)) {
        throw '処理中にconfig.jsonが変更されたため中止しました。もう一度実行してください。'
    }
    [IO.File]::Replace($temporaryPath, $configPath, $backup)
    $temporaryPath = $null
    Write-Host 'PC Engine / CD-ROM2 / PC-FXのグループに更新しました。' -ForegroundColor Green
    Write-Host '表示比率・fps・各機種の時間など、その他の設定値は維持しています。'
    Write-Host "元の設定のバックアップ: $backup"
    if (@($config.single_system_mode.disabled_systems) -contains 'pcfx') {
        Write-Host 'pcfxはdisabled_systemsで停止中です。その設定は保持しています。' -ForegroundColor Yellow
    }
    exit 0
} catch {
    Write-Host ('更新できませんでした: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
} finally {
    if ($temporaryPath -and (Test-Path -LiteralPath $temporaryPath)) { Remove-Item -LiteralPath $temporaryPath }
}
