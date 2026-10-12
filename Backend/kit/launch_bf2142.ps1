# BF2142 launcher: borderless window (default), normal window or exclusive fullscreen.
#
#   launch_bf2142.ps1 [-Mode borderless|window|fullscreen] [-Mod Project_Remaster_v17]
#                     [-Width 1600 -Height 900] [-Exe BF2142_selfhost.exe] [-Join IP]
#
# Borderless = the game runs windowed at the monitor resolution, this script strips the
# window frame and keeps it stripped (the game may restore it after Alt+Tab). Unlike
# exclusive DirectX 9 fullscreen, Alt+Tab is instant and other windows can come on top.

param(
    [ValidateSet("borderless", "window", "fullscreen")]
    [string]$Mode = "borderless",
    [string]$Mod = "",
    [int]$Width = 0,
    [int]$Height = 0,
    [string]$Exe = "BF2142_selfhost.exe",
    [string]$Join = ""
)

$ErrorActionPreference = "Stop"
$gameDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Add-Type -AssemblyName System.Windows.Forms
$screen = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
if ($Width -le 0) { $Width = $screen.Width }
if ($Height -le 0) { $Height = $screen.Height }

$gameArgs = @()
if ($Mod) { $gameArgs += "+modPath", "mods/$Mod" }
$gameArgs += "+widescreen", "1"
if ($Mode -eq "fullscreen") {
    # Project Remaster sets renderer.setFullScreen 0 in Settings\VideoDefault.con, so fullscreen
    # must be requested explicitly; the resolution and refresh rate come from the game profile.
    $gameArgs += "+fullscreen", "1"
} else {
    $gameArgs += "+fullscreen", "0", "+szx", "$Width", "+szy", "$Height"
}
if ($Join) { $gameArgs += "+joinServer", $Join, "+port", "17567" }

# In-game antialiasing makes Project Remaster render a black world on modern GPUs and crash on
# Alt+Tab, so switch it off in every game profile before the game reads them.
if ($Mod) {
    try {
        $profiles = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "Battlefield 2142\Profiles"
        $latin1 = [Text.Encoding]::GetEncoding(28591)
        Get-ChildItem -LiteralPath $profiles -Recurse -Filter Video.con -ErrorAction SilentlyContinue | ForEach-Object {
            $text = [IO.File]::ReadAllText($_.FullName, $latin1)
            $fixed = $text -replace '(?m)^(VideoSettings\.setAntialiasing)[ \t]+\S+', '$1 Off'
            if ($fixed -ne $text) { [IO.File]::WriteAllText($_.FullName, $fixed, $latin1) }
        }
    } catch { }
}

$proc = Start-Process -FilePath (Join-Path $gameDir $Exe) -WorkingDirectory $gameDir -ArgumentList $gameArgs -PassThru

Add-Type @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public static class BfWin {
    [DllImport("user32.dll")] public static extern int GetWindowLong(IntPtr hWnd, int nIndex);
    [DllImport("user32.dll")] public static extern int SetWindowLong(IntPtr hWnd, int nIndex, int dwNewLong);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr hWnd, IntPtr after, int x, int y, int cx, int cy, uint flags);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool IsHungAppWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr hWnd, int cmd);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc cb, IntPtr lParam);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetClassName(IntPtr hWnd, StringBuilder s, int n);
    [DllImport("user32.dll")] static extern IntPtr GetWindow(IntPtr hWnd, uint cmd);
    delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }

    static readonly IntPtr TOPMOST = new IntPtr(-1), NOTOPMOST = new IntPtr(-2);
    // SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_ASYNCWINDOWPOS: не ждём зависшее окно
    const uint ZFLAGS = 0x0001 | 0x0002 | 0x0010 | 0x4000;

    static string Class(IntPtr h) { var s = new StringBuilder(64); GetClassName(h, s, 64); return s.ToString(); }

    // Видимые окна верхнего уровня процессов из pids (без владельца — то есть главные).
    public static List<IntPtr> Windows(int[] pids) {
        var found = new List<IntPtr>();
        var set = new HashSet<uint>();
        foreach (var p in pids) set.Add((uint)p);
        EnumWindows((h, l) => {
            uint pid;
            GetWindowThreadProcessId(h, out pid);
            if (set.Contains(pid) && IsWindowVisible(h) && GetWindow(h, 4) == IntPtr.Zero) found.Add(h);
            return true;
        }, IntPtr.Zero);
        return found;
    }

    // "Призраки" зависших окон (их рисует система вместо окна, которое не отвечает).
    public static List<IntPtr> Ghosts() {
        var found = new List<IntPtr>();
        EnumWindows((h, l) => { if (IsWindowVisible(h) && Class(h) == "Ghost") found.Add(h); return true; }, IntPtr.Zero);
        return found;
    }

    public static void Demote(IntPtr h) { SetWindowPos(h, NOTOPMOST, 0, 0, 0, 0, ZFLAGS); }
    public static void Promote(IntPtr h) { SetWindowPos(h, TOPMOST, 0, 0, 0, 0, ZFLAGS); }
    public static void Minimize(IntPtr h) { ShowWindowAsync(h, 6); }  // SW_MINIMIZE
}
"@

$GWL_STYLE = -16
# WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX
$FRAME = 0x00C00000 -bor 0x00040000 -bor 0x00080000 -bor 0x00020000 -bor 0x00010000
# SWP_FRAMECHANGED | SWP_NOZORDER | SWP_NOACTIVATE: never steal focus or change window order
$SWP_FLAGS = 0x0020 -bor 0x0004 -bor 0x0010

# Пока игра запущена:
#  - Диспетчер задач всегда поверх игры: пока он открыт, окно игры (и «призрак» зависшего окна)
#    не может быть «поверх всех», а сам диспетчер поднимается наверх (если он не запущен
#    от администратора — тогда это делает его собственная галочка «Поверх остальных окон»);
#  - в полноэкранном режиме DirectX 9 ничего не пускает поверх себя, поэтому, когда диспетчер
#    открывают или переключаются на него (Ctrl+Shift+Esc), игра сворачивается; зависшая — тоже;
#  - в режиме без рамки окно держится без рамки и на весь экран.
$tmWasActive = $false
while (-not $proc.HasExited) {
    Start-Sleep -Milliseconds 500
    $proc.Refresh()
    $hwnd = $proc.MainWindowHandle

    $tmPids = @(Get-Process taskmgr -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
    $tm = @()
    if ($tmPids.Count) { $tm = @([BfWin]::Windows($tmPids) | Where-Object { -not [BfWin]::IsIconic($_) }) }
    if ($tm.Count) {
        $fg = [BfWin]::GetForegroundWindow()
        $tmActive = $tm -contains $fg
        $game = @([BfWin]::Windows(@($proc.Id))) + @([BfWin]::Ghosts())
        $hung = ($hwnd -ne [IntPtr]::Zero) -and [BfWin]::IsHungAppWindow($hwnd)
        foreach ($w in $game) { [BfWin]::Demote($w) }
        if ($tmActive -and -not $tmWasActive -and ($Mode -eq "fullscreen" -or $hung)) {
            foreach ($w in $game) { [BfWin]::Minimize($w) }
        }
        foreach ($w in $tm) { [BfWin]::Promote($w) }
        $tmWasActive = $tmActive
    } else {
        $tmWasActive = $false
    }

    if ($Mode -ne "borderless") { continue }
    # Leave a minimized game alone, otherwise it would pop back up after Alt+Tab.
    if ($hwnd -eq [IntPtr]::Zero -or [BfWin]::IsIconic($hwnd)) { continue }
    $style = [BfWin]::GetWindowLong($hwnd, $GWL_STYLE)
    $rect = New-Object BfWin+RECT
    [void][BfWin]::GetWindowRect($hwnd, [ref]$rect)
    $placed = ($rect.Left -eq $screen.X) -and ($rect.Top -eq $screen.Y) -and
              (($rect.Right - $rect.Left) -eq $Width) -and (($rect.Bottom - $rect.Top) -eq $Height)
    if ((($style -band $FRAME) -ne 0) -or -not $placed) {
        [void][BfWin]::SetWindowLong($hwnd, $GWL_STYLE, ($style -band (-bnot $FRAME)))
        [void][BfWin]::SetWindowPos($hwnd, [IntPtr]::Zero, $screen.X, $screen.Y, $Width, $Height, $SWP_FLAGS)
    }
}
