[CmdletBinding(PositionalBinding = $false)]
param(
    [string]$Distribution = 'Ubuntu-22.04',
    [string]$BoardIP,
    [switch]$PrepareOnly,
    [Parameter(Position = 0, ValueFromRemainingArguments = $true)]
    [string[]]$LaunchArguments
)
$ErrorActionPreference = 'Stop'
if ($BoardIP) {
    $parsedAddress = [System.Net.IPAddress]::Parse($BoardIP)
    if ($parsedAddress.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
        throw 'BoardIP must be an IPv4 address.'
    }
}
$portableWindowsTools = $PSScriptRoot.Replace('\', '/')
$pathResult = @(& wsl -d $Distribution --exec wslpath -a -u $portableWindowsTools)
if ($LASTEXITCODE -ne 0 -or $pathResult.Count -ne 1) { throw 'Unable to resolve the script directory in WSL.' }
$wslTools = $pathResult[0].Trim()
$environmentArguments = @()
if ($BoardIP) { $environmentArguments += "MARSDOG_BOARD_IP=$BoardIP" }
if ($PrepareOnly) { $LaunchArguments = @('--prepare-only') }
& wsl -d $Distribution --exec env @environmentArguments bash "$wslTools/start-remote-viz.sh" @LaunchArguments
exit $LASTEXITCODE
