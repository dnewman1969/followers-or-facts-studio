<#
  Puts a "Followers or Facts Studio" icon on the desktop and in the Start menu.
  Uses Windows' real Desktop folder, which is inside OneDrive on many PCs.
#>
$ErrorActionPreference = "Stop"
$repo = Split-Path $PSScriptRoot -Parent
$pythonw = Join-Path $repo ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pythonw)) {
    Write-Error "The Studio isn't installed yet. Run setup.ps1 first."
}
$icon = Join-Path $repo "brand\owlbert.ico"
$shell = New-Object -ComObject WScript.Shell
$places = @(
    [Environment]::GetFolderPath("Desktop"),
    (Join-Path ([Environment]::GetFolderPath("Programs")) "")
)
foreach ($folder in $places) {
    $lnk = $shell.CreateShortcut((Join-Path $folder "Followers or Facts Studio.lnk"))
    $lnk.TargetPath = $pythonw
    $lnk.Arguments = "-m fofstudio app"
    $lnk.WorkingDirectory = $repo
    $lnk.IconLocation = "$icon,0"
    $lnk.Description = "Starts Ollama and ComfyUI, then opens Followers or Facts Studio"
    $lnk.Save()
    Write-Host "Icon made in $folder"
}
