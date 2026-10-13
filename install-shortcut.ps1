# Puts a "gearshift-cc" icon on the Desktop and in the Start menu. Click it to open the shifter window.
$dir = $PSScriptRoot
$pyw = Join-Path (Split-Path (Get-Command python).Source) 'pythonw.exe'  # pythonw: no console window behind it
$sh = New-Object -ComObject WScript.Shell
foreach ($folder in [Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs')) {
    $lnk = $sh.CreateShortcut((Join-Path $folder 'gearshift-cc.lnk'))
    $lnk.TargetPath = $pyw
    $lnk.Arguments = '-m gearbox.gui'
    $lnk.WorkingDirectory = $dir
    $lnk.IconLocation = (Join-Path $dir 'gearbox-icon.ico')
    $lnk.Save()
    Write-Output "Created $($lnk.FullName)"
}
