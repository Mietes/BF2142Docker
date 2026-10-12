# Установщик для игры на нашем сервере BF2142 (Project Remaster v17).
# Запускается из INSTALL.bat / UNINSTALL.bat (в полной сборке — сам после распаковки).
#
# Два режима — определяются по содержимому папки files\:
#   комплект — для уже установленной игры: рядом лежат архивы патча Штаба и локализация;
#   сборка   — игра распакована из нашего установщика: патч Штаба уже в ней, зато нужно
#              прописать игру в реестр (путь, язык, CD-ключ), как это делает обычный установщик.
# Что делается в обоих режимах:
#   - копия BF2142.exe -> BF2142_selfhost.exe с адресом сервера (оригинал не трогается);
#   - лаунчер launch_bf2142.ps1 и ярлык «BF2142 Remaster» на рабочем столе;
#   - выключается сглаживание в профилях игры (с ним Remaster показывает чёрный мир).
# Повторный запуск безопасен: так меняют адрес сервера.

param(
    [switch]$Uninstall,
    [string]$Address = "",
    [string]$Language = "",
    [string]$GameDir = "",
    [string]$ShortcutDir = "",
    [string]$RegistryRoot = "",
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"
$Files = Split-Path -Parent $MyInvocation.MyCommand.Path
$KitRoot = Split-Path -Parent $Files
$Mod = "Project_Remaster_v17"
$ExeOut = "BF2142_selfhost.exe"
$Marker = "selfhost_kit.txt"
$MountTag = "rem selfhost: HQ unlocks page for Project Remaster (Backend/tools/build_hq_patch.py)"
$Zips = @("Menu_selfhost_hq_server.zip", "Menu_selfhost_hq_client.zip")
$BuildMode = -not (Test-Path -LiteralPath (Join-Path $Files $Zips[1]))
$ShortcutName = "BF2142 Remaster"
$ShortcutArgs = "-Mode fullscreen -Mod $Mod"
$Languages = [ordered]@{
    "1" = @{ Name = "Russian"; Locale = "ru"; Title = "Русский" }
    "2" = @{ Name = "English"; Locale = "en"; Title = "English" }
    "3" = @{ Name = "German"; Locale = "de"; Title = "Deutsch" }
}
# Строки в BF2142.exe 1.51, где записаны адреса серверов, и сколько символов там можно писать
# (то же, что Backend/tools/patch_client.py).
$Slots = @{
    0x5639A4 = 31; 0x5639C4 = 23; 0x563CC4 = 0; 0x59E6E8 = 24; 0x59E938 = 37
    0x59F608 = 19; 0x6067A0 = 63; 0x607180 = 63; 0x6071C0 = 63
}
# Проверка «есть ли интернет»: игра резолвит этот домен и ea.com. Сборка вписала сюда свой
# домен — ставим ea.com, чтобы игра не обращалась к чужому серверу.
$DnsCheckOffset = 0x524824
$DnsCheckHost = "ea.com"
$SslCheckOffset = 0x45FE8D
$SslCheckPatched = [byte[]](0xB8, 0x15, 0x00, 0x00, 0x00)
$Latin1 = [Text.Encoding]::GetEncoding(28591)

function Say([string]$ru, [string]$en = "") {
    Write-Host $ru
    if ($en) { Write-Host "  $en" -ForegroundColor DarkGray }
}

function Stop-Kit([string]$ru, [string]$en = "") {
    throw (New-Object System.Exception ("$ru`n$en"))
}

function Pause-Kit {
    if (-not $NoPause) { [void](Read-Host "`nНажми Enter / Press Enter") }
}

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    return (New-Object Security.Principal.WindowsPrincipal $id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Restart-Elevated([string]$game, [string]$why) {
    Say "$why — Windows спросит разрешение." "Administrator rights are needed."
    $argList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"", "-GameDir", "`"$game`"")
    if ($Uninstall) { $argList += "-Uninstall" }
    if ($script:ResolvedAddress) { $argList += "-Address", $script:ResolvedAddress }
    if ($script:ResolvedLanguage) { $argList += "-Language", $script:ResolvedLanguage }
    if ($ShortcutDir) { $argList += "-ShortcutDir", "`"$ShortcutDir`"" }
    Start-Process powershell.exe -Verb RunAs -ArgumentList $argList
    exit 0
}

# --- папка игры ----------------------------------------------------------------

function Test-GameDir([string]$dir) {
    return $dir -and (Test-Path -LiteralPath (Join-Path $dir "BF2142.exe"))
}

function Find-GameDir {
    if ($GameDir) {  # папку указали явно — только она, без поиска
        if (Test-GameDir $GameDir) { return (Resolve-Path -LiteralPath $GameDir).Path }
        Stop-Kit "В папке $GameDir нет BF2142.exe." "No BF2142.exe in $GameDir."
    }
    $candidates = @()
    $p = $KitRoot
    for ($i = 0; $i -lt 3 -and $p; $i++) { $candidates += $p; $p = Split-Path -Parent $p }
    if (-not $BuildMode) {  # сборка всегда лежит вокруг установщика, реестр ей не нужен
        foreach ($key in "HKLM:\SOFTWARE\WOW6432Node\Electronic Arts\EA Games\Battlefield 2142",
                         "HKLM:\SOFTWARE\Electronic Arts\EA Games\Battlefield 2142") {
            try { $candidates += (Get-ItemProperty -Path $key -ErrorAction Stop).InstallDir } catch { }
        }
    }
    foreach ($c in $candidates) { if (Test-GameDir $c) { return (Resolve-Path -LiteralPath $c).Path } }

    Say "Папка игры не найдена автоматически — укажи её (где лежит BF2142.exe)." `
        "Game folder not found - please select it (the one with BF2142.exe)."
    Add-Type -AssemblyName System.Windows.Forms
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = "Battlefield 2142 (BF2142.exe)"
    if ($dialog.ShowDialog() -eq "OK" -and (Test-GameDir $dialog.SelectedPath)) { return $dialog.SelectedPath }
    Stop-Kit "BF2142.exe не найден." "BF2142.exe not found."
}

function Assert-Writable([string]$dir) {
    $probe = Join-Path $dir "selfhost_write_test.tmp"
    try {
        [IO.File]::WriteAllText($probe, "x")
        Remove-Item -LiteralPath $probe -Force
    } catch [UnauthorizedAccessException] {
        Restart-Elevated $dir "Нужны права администратора для записи в $dir"
    }
}

# --- адрес сервера и язык ------------------------------------------------------

function Get-ServerAddress {
    $value = $Address
    $file = Join-Path $KitRoot "server.txt"
    if (-not $value -and (Test-Path -LiteralPath $file)) {
        foreach ($line in Get-Content -LiteralPath $file) {
            if ($line -match '^\s*address\s*=\s*(\S+)') { $value = $Matches[1] }
        }
    }
    while ($true) {
        if (-not $value) {
            $value = (Read-Host "Адрес сервера (IP, например 203.0.113.10) / Server address").Trim()
        }
        if ($value -match '^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?::(\d{1,5}))?$') {
            $octets = 1..4 | ForEach-Object { [int]$Matches[$_] }
            $port = if ($Matches[5]) { [int]$Matches[5] } else { 80 }
            if (-not ($octets | Where-Object { $_ -gt 255 }) -and $port -ge 1 -and $port -le 65535) {
                return @{ Ip = ($octets -join "."); Port = $port }
            }
        }
        Say "Неверный адрес: '$value'. Нужен IPv4, например 203.0.113.10 (порт — только если сказали)." `
            "Invalid address. Use IPv4 like 203.0.113.10 (add :port only if told to)."
        $value = ""
    }
}

function Get-GameLanguage {
    foreach ($l in $Languages.Values) {
        if ($Language -and ($Language -eq $l.Name -or $Language -eq $l.Locale)) { return $l }
    }
    $culture = (Get-Culture).TwoLetterISOLanguageName
    $default = if ($culture -in "ru", "uk", "be", "kk") { "1" } elseif ($culture -eq "de") { "3" } else { "2" }
    $menu = ($Languages.Keys | ForEach-Object { "$_ - $($Languages[$_].Title)" }) -join ", "
    while ($true) {
        $answer = (Read-Host "Язык игры / Game language ($menu) [$default]").Trim()
        if (-not $answer) { $answer = $default }
        if ($Languages.Contains($answer)) { return $Languages[$answer] }
    }
}

# --- exe -------------------------------------------------------------------------

function Read-CStr([byte[]]$data, [int]$off) {
    $end = [Array]::IndexOf($data, [byte]0, $off)
    return [Text.Encoding]::ASCII.GetString($data, $off, $end - $off)
}

function Write-CStr([byte[]]$data, [int]$off, [string]$text, [int]$limit) {
    $bytes = [Text.Encoding]::ASCII.GetBytes($text)
    for ($i = 0; $i -le $limit; $i++) { $data[$off + $i] = if ($i -lt $bytes.Length) { $bytes[$i] } else { 0 } }
}

function New-PatchedExe([string]$game, [string]$ip, [int]$port) {
    $data = [IO.File]::ReadAllBytes((Join-Path $game "BF2142.exe"))
    for ($i = 0; $i -lt 5; $i++) {
        if ($data[$SslCheckOffset + $i] -ne $SslCheckPatched[$i]) {
            Stop-Kit "Этот BF2142.exe не подходит: нужен exe версии 1.51 из нашей сборки игры." `
                     "This BF2142.exe is not supported: the 1.51 exe from our game build is required."
        }
    }
    $oldHost = Read-CStr $data 0x607180
    if (-not $oldHost -or $oldHost.Contains("%")) { Stop-Kit "Неожиданный BF2142.exe." "Unexpected BF2142.exe." }
    $hostPort = if ($port -eq 80) { $ip } else { "${ip}:$port" }
    foreach ($off in $Slots.Keys) {
        $old = Read-CStr $data $off
        if (-not $old.Contains($oldHost)) {
            Stop-Kit "Этот BF2142.exe не подходит (другая версия)." "This BF2142.exe is a different version."
        }
        $new = if ($old.StartsWith("http://")) { $old.Replace($oldHost, $hostPort) } else { $old.Replace($oldHost, $ip) }
        $end = $off + $old.Length
        while ($data[$end] -eq 0) { $end++ }
        $limit = [Math]::Min([Math]::Max($Slots[$off], $old.Length), $end - $off - 1)
        if ($new.Length -gt $limit) { $new = $old.Replace($oldHost, $ip) }  # новости без порта — не критично
        if ($new.Length -gt $limit) { Stop-Kit "Адрес не помещается в exe." "The address does not fit into the exe." }
        Write-CStr $data $off $new $limit
    }
    $dns = Read-CStr $data $DnsCheckOffset
    if ($dns -ne $DnsCheckHost) {
        if (-not $dns -or -not $oldHost.EndsWith($dns) -or $dns.Length -lt $DnsCheckHost.Length) {
            Stop-Kit "Этот BF2142.exe не подходит (другая версия)." "This BF2142.exe is a different version."
        }
        Write-CStr $data $DnsCheckOffset $DnsCheckHost $dns.Length
    }
    # Large Address Aware: без него Remaster не помещается в 2 ГБ и падает при загрузке карты.
    $pos = [BitConverter]::ToInt32($data, 0x3C) + 22
    $flags = [BitConverter]::ToUInt16($data, $pos) -bor 0x20
    $data[$pos] = $flags -band 0xFF
    $data[$pos + 1] = ($flags -shr 8) -band 0xFF
    try {
        [IO.File]::WriteAllBytes((Join-Path $game $ExeOut), $data)
    } catch {
        Stop-Kit "Не удалось записать $ExeOut — закрой игру и запусти установку снова." `
                 "Could not write $ExeOut - close the game and run the installer again."
    }
}

# --- Remaster: Штаб и локализация (только комплект) --------------------------------

function Get-Md5([string]$path) {
    return (Get-FileHash -LiteralPath $path -Algorithm MD5).Hash.ToLower()
}

function Read-Expected {
    $expected = @{}
    foreach ($line in Get-Content -LiteralPath (Join-Path $Files "remaster.md5")) {
        if ($line -match '^(\w+)=(\w+)$') { $expected[$Matches[1]] = $Matches[2] }
    }
    return $expected
}

function Set-Mount([string]$con, [string]$archive, [bool]$present) {
    $text = [IO.File]::ReadAllText($con, $Latin1)
    $lines = $text -split "`n"
    $line = "fileManager.mountArchive $archive Menu"
    $keep = @($lines | Where-Object { -not $_.Contains($MountTag) -and -not $_.Contains("Menu_selfhost_hq_") })
    if ($present) {
        $at = 0
        while ($at -lt $keep.Count -and -not $keep[$at].Trim().ToLower().StartsWith("filemanager.mountarchive")) { $at++ }
        $eol = if ($lines[0].EndsWith("`r")) { "`r" } else { "" }
        $before = if ($at -gt 0) { $keep[0..($at - 1)] } else { @() }
        $after = if ($at -lt $keep.Count) { $keep[$at..($keep.Count - 1)] } else { @() }
        $keep = @($before) + @("$MountTag$eol", "$line$eol") + @($after)
    }
    $new = $keep -join "`n"
    if ($new -ne $text) { [IO.File]::WriteAllText($con, $new, $Latin1) }
}

function Install-Hq([string]$game) {
    $remaster = Join-Path $game "mods\$Mod"
    if (-not (Test-Path -LiteralPath (Join-Path $remaster "Objects\Menu_server.zip"))) {
        Stop-Kit "Не найден Project Remaster v17 (mods\$Mod). Сначала установи его." `
                 "Project Remaster v17 (mods\$Mod) not found. Install it first."
    }
    $expected = Read-Expected
    if ((Get-Md5 (Join-Path $remaster "Objects\Menu_server.zip")) -ne $expected["menu_server"]) {
        Stop-Kit "Версия Project Remaster отличается от той, под которую сделан патч (нужна v17)." `
                 "Your Project Remaster differs from the one this kit was made for (v17 required)."
    }
    $loc = Join-Path $remaster "Localization\strings.csv"
    $backup = "$loc.selfhost_orig"
    if (-not (Test-Path -LiteralPath $backup)) {
        $current = Get-Md5 $loc
        if ($current -eq $expected["strings_original"]) {
            Copy-Item -LiteralPath $loc -Destination $backup
        } elseif ($current -ne $expected["strings_patched"]) {
            Stop-Kit "Файл локализации Remaster изменён кем-то ещё (Localization\strings.csv)." `
                     "Remaster's Localization\strings.csv was modified by something else."
        }
    }
    Copy-Item -LiteralPath (Join-Path $Files "strings.csv") -Destination $loc -Force
    foreach ($zip in $Zips) {
        Copy-Item -LiteralPath (Join-Path $Files $zip) -Destination (Join-Path $remaster "Objects\$zip") -Force
    }
    Set-Mount (Join-Path $remaster "ServerArchives.con") "Objects/$($Zips[0])" $true
    Set-Mount (Join-Path $remaster "ClientArchives.con") "Objects/$($Zips[1])" $true
}

function Remove-Hq([string]$game) {
    $remaster = Join-Path $game "mods\$Mod"
    if (-not (Test-Path -LiteralPath $remaster)) { return }
    foreach ($pair in @(@("ServerArchives.con", $Zips[0]), @("ClientArchives.con", $Zips[1]))) {
        $con = Join-Path $remaster $pair[0]
        if (Test-Path -LiteralPath $con) { Set-Mount $con "Objects/$($pair[1])" $false }
        Remove-Item -LiteralPath (Join-Path $remaster "Objects\$($pair[1])") -Force -ErrorAction SilentlyContinue
    }
    $loc = Join-Path $remaster "Localization\strings.csv"
    if (Test-Path -LiteralPath "$loc.selfhost_orig") {
        Copy-Item -LiteralPath "$loc.selfhost_orig" -Destination $loc -Force
        Remove-Item -LiteralPath "$loc.selfhost_orig" -Force
    }
}

# --- реестр (только сборка) ------------------------------------------------------

function Get-RegRoot {
    if ($RegistryRoot) { return $RegistryRoot }
    if ([Environment]::Is64BitOperatingSystem) { return "HKLM:\SOFTWARE\WOW6432Node\Electronic Arts\EA GAMES\Battlefield 2142" }
    return "HKLM:\SOFTWARE\Electronic Arts\EA GAMES\Battlefield 2142"
}

function Get-RegExePath([string]$psPath) {
    return $psPath -replace '^HKLM:\\', 'HKLM\' -replace '^HKCU:\\', 'HKCU\'
}

function New-CdKey {
    $chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789".ToCharArray()
    return -join (1..25 | ForEach-Object { $chars | Get-Random })
}

function Set-GameRegistry([string]$game, $lang) {
    $root = Get-RegRoot
    $backup = Join-Path $KitRoot "registry_backup.reg"
    if (-not (Test-Path -LiteralPath $backup)) {  # что было до нас — для UNINSTALL.bat
        if (Test-Path -LiteralPath $root) {
            & reg.exe export (Get-RegExePath $root) $backup /y | Out-Null
        } else {
            [IO.File]::WriteAllText($backup, ";none")
        }
    }
    $values = [ordered]@{
        "ApplicationName" = "Battlefield 2142"; "BuildNr" = "1.10.77.0"; "Version" = "1.51"
        "DisplayName" = "Battlefield 2142"; "ProductName" = "Battlefield 2142 Remaster"
        "InstallDir" = $game; "Folder" = $game; "CD Drive" = $game; "Installed From" = $game; "Product GUID" = $game
        "Language" = $lang.Name; "Locale" = $lang.Locale; "Suppression Exe" = ""; "Registration" = ""
    }
    New-Item -Path $root -Force | Out-Null
    foreach ($k in $values.Keys) { Set-ItemProperty -LiteralPath $root -Name $k -Value $values[$k] }
    $sub = Join-Path $root "1.0"
    New-Item -Path $sub -Force | Out-Null
    Set-ItemProperty -LiteralPath $sub -Name "DisplayName" -Value "Battlefield 2142"
    Set-ItemProperty -LiteralPath $sub -Name "LanguageName" -Value $lang.Name
    Set-ItemProperty -LiteralPath $sub -Name "ProgramGroup" -Value $game
    New-ItemProperty -LiteralPath $sub -Name "Language" -PropertyType DWord -Value 0x10 -Force | Out-Null
    $ergc = Join-Path $root "ergc"
    $key = ""
    try { $key = (Get-ItemProperty -LiteralPath $ergc -ErrorAction Stop)."(default)" } catch { }
    if (-not $key) {  # CD-ключ: сервер его не проверяет, но игре он нужен в реестре
        New-Item -Path $ergc -Force | Out-Null
        Set-ItemProperty -LiteralPath $ergc -Name "(default)" -Value (New-CdKey)
    }
}

function Restore-GameRegistry {
    $backup = Join-Path $KitRoot "registry_backup.reg"
    if (-not (Test-Path -LiteralPath $backup)) { return }
    $root = Get-RegRoot
    if ((Get-Content -LiteralPath $backup -TotalCount 1) -eq ";none") {
        Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
    } else {
        Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
        & reg.exe import $backup 2>$null | Out-Null
    }
    Remove-Item -LiteralPath $backup -Force
}

# --- ярлык и профили -----------------------------------------------------------

function Get-ShortcutDir {
    if ($ShortcutDir) { return $ShortcutDir }
    return [Environment]::GetFolderPath("Desktop")
}

function New-GameShortcut([string]$game) {
    $path = Join-Path (Get-ShortcutDir) "$ShortcutName.lnk"
    $lnk = (New-Object -ComObject WScript.Shell).CreateShortcut($path)
    $lnk.TargetPath = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    $lnk.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$game\launch_bf2142.ps1`" $ShortcutArgs"
    $lnk.WorkingDirectory = $game
    $lnk.IconLocation = "$game\BF2142.exe,0"
    $lnk.WindowStyle = 7
    $lnk.Description = "Battlefield 2142: Project Remaster v17"
    $lnk.Save()
    return $path
}

function Disable-Antialiasing {
    $profiles = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "Battlefield 2142\Profiles"
    $count = 0
    Get-ChildItem -LiteralPath $profiles -Recurse -Filter Video.con -ErrorAction SilentlyContinue | ForEach-Object {
        $text = [IO.File]::ReadAllText($_.FullName, $Latin1)
        $fixed = $text -replace '(?m)^(VideoSettings\.setAntialiasing)[ \t]+\S+', '$1 Off'
        if ($fixed -ne $text) { [IO.File]::WriteAllText($_.FullName, $fixed, $Latin1); $count++ }
    }
    return $count
}

# --- установка и удаление ------------------------------------------------------

function Install-Kit {
    $script:ResolvedAddress = ""
    $script:ResolvedLanguage = ""
    $game = Find-GameDir
    Say "Папка игры / Game folder: $game"
    $server = Get-ServerAddress
    $script:ResolvedAddress = if ($server.Port -eq 80) { $server.Ip } else { "$($server.Ip):$($server.Port)" }
    $lang = $null
    if ($BuildMode) {
        $lang = Get-GameLanguage
        $script:ResolvedLanguage = $lang.Locale
        if (-not $RegistryRoot -and -not (Test-Admin)) {
            Restart-Elevated $game "Нужны права администратора, чтобы прописать игру в реестр"
        }
    }
    Assert-Writable $game

    Say "1/5 Копия exe с адресом $($script:ResolvedAddress) -> $ExeOut" "Patched copy of the exe"
    New-PatchedExe $game $server.Ip $server.Port
    if ($BuildMode) {
        Say "2/5 Реестр: путь к игре, язык ($($lang.Title)), CD-ключ" "Registry: game path, language, CD key"
        Set-GameRegistry $game $lang
    } else {
        Say "2/5 Штаб: страница поощрений и локализация Remaster" "HQ unlocks page and Remaster localization"
        Install-Hq $game
    }
    Say "3/5 Лаунчер и ярлык «$ShortcutName» на рабочем столе" "Launcher and desktop shortcut"
    $launcher = Join-Path $Files "launch_bf2142.ps1"
    if (Test-Path -LiteralPath $launcher) {
        Copy-Item -LiteralPath $launcher -Destination (Join-Path $game "launch_bf2142.ps1") -Force
    }
    $made = New-GameShortcut $game
    Say "4/5 Сглаживание выключено в профилях: $(Disable-Antialiasing)" "Antialiasing turned off in game profiles"
    $info = @("address=$($script:ResolvedAddress)", "mode=$(if ($BuildMode) { 'build' } else { 'kit' })",
              "installed=$(Get-Date -Format 'yyyy-MM-dd HH:mm')", "shortcut=$made")
    [IO.File]::WriteAllLines((Join-Path $game $Marker), [string[]]$info)
    Say "5/5 Готово! Запускай игру ярлыком «$ShortcutName» на рабочем столе." `
        "Done! Start the game with the '$ShortcutName' desktop shortcut."
}

function Uninstall-Kit {
    $game = Find-GameDir
    Say "Папка игры / Game folder: $game"
    if ($BuildMode -and -not $RegistryRoot -and -not (Test-Admin)) {
        Restart-Elevated $game "Нужны права администратора, чтобы убрать игру из реестра"
    }
    Assert-Writable $game
    $markerPath = Join-Path $game $Marker
    if (Test-Path -LiteralPath $markerPath) {
        foreach ($line in Get-Content -LiteralPath $markerPath) {
            if ($line -match '^shortcut=(.+)$') { Remove-Item -LiteralPath $Matches[1] -Force -ErrorAction SilentlyContinue }
        }
        Remove-Item -LiteralPath $markerPath -Force
        if (-not $BuildMode) { Remove-Item -LiteralPath (Join-Path $game "launch_bf2142.ps1") -Force -ErrorAction SilentlyContinue }
    }
    Remove-Item -LiteralPath (Join-Path $game $ExeOut) -Force -ErrorAction SilentlyContinue
    if ($BuildMode) {
        Restore-GameRegistry
        Say "`nИгра убрана из реестра, ярлык удалён. Папку игры теперь можно просто удалить:`n  $game" `
            "Registry entries and the shortcut are removed. You can now delete the game folder."
    } else {
        Remove-Hq $game
        Say "`nКомплект удалён, игра в исходном виде." "The kit is removed, the game is back to original."
    }
}

try {
    if ($Uninstall) { Uninstall-Kit } else { Install-Kit }
    Pause-Kit
} catch {
    Write-Host "`nОШИБКА / ERROR:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Pause-Kit
    exit 1
}
