# 在桌面建立 SmartCook 展場介面的捷徑（指向 start_smartcook.bat）
#   powershell -ExecutionPolicy Bypass -File create_desktop_shortcut.ps1             # 連實體手臂
#   powershell -ExecutionPolicy Bypass -File create_desktop_shortcut.ps1 -Simulate   # 模擬模式，不連手臂
param(
    [switch]$Simulate,
    [string]$Root = $PSScriptRoot
)

$bat = Join-Path $Root 'start_smartcook.bat'
if (-not (Test-Path $bat)) {
    Write-Error "找不到 $bat"
    exit 1
}

$name = if ($Simulate) { 'SmartCook 展場介面（模擬）' } else { 'SmartCook 展場介面' }
$path = Join-Path ([Environment]::GetFolderPath('Desktop')) "$name.lnk"

$lnk = (New-Object -ComObject WScript.Shell).CreateShortcut($path)
$lnk.TargetPath = $bat
$lnk.Arguments = if ($Simulate) { '--simulate' } else { '' }
$lnk.WorkingDirectory = $Root
$lnk.IconLocation = "$env:SystemRoot\System32\shell32.dll,24"
$lnk.Description = 'SmartCook 展場觸控介面'
$lnk.Save()

Write-Host "已建立捷徑：$path"
