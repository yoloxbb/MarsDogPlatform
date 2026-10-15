[CmdletBinding()]
param(
    [string]$PreferredIP,
    [string]$IdentityPath,
    [switch]$ForceDiscovery,
    [switch]$DiscoverOnly
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
if (-not $IdentityPath) { $IdentityPath = Join-Path $PSScriptRoot 'board-identity.json' }
. (Join-Path $PSScriptRoot 'network-discovery.ps1')
$identity = Get-Content -LiteralPath $IdentityPath -Raw | ConvertFrom-Json
if ($identity.board_id -notmatch '^[0-9a-f]{64}$' -or $identity.ssh_key_type -ne 'ssh-ed25519') {
    throw 'Invalid paired board identity.'
}
$networkDirectory = Join-Path $env:LOCALAPPDATA 'MarsDog\remote-visualization'
New-Item -ItemType Directory -Path $networkDirectory -Force | Out-Null
$cacheFile = Join-Path $networkDirectory 'network-current.json'
$addresses = @(Get-MarsDogLocalIPv4)
if ($addresses.Count -eq 0) { throw 'No active LAN IPv4 interface was found.' }
$boardAddress = $null
$source = 'mdns-verified'
if (-not $ForceDiscovery) {
    $candidates = @($PreferredIP)
    if (Test-Path -LiteralPath $cacheFile) {
        try { $candidates += (Get-Content -LiteralPath $cacheFile -Raw | ConvertFrom-Json).boardIP } catch {}
    }
    foreach ($candidate in ($candidates | Where-Object { $_ } | Select-Object -Unique)) {
        if (Test-MarsDogHostKey -IPAddress $candidate -Identity $identity) {
            $boardAddress = $candidate; $source = 'cached-verified'; break
        }
    }
}
if (-not $boardAddress) {
    $candidates = [MarsDog.MdnsDiscovery]::Discover($addresses, $identity.service_instance, $identity.board_id, 8)
    foreach ($candidate in $candidates) {
        if (Test-MarsDogHostKey -IPAddress $candidate -Identity $identity) { $boardAddress = $candidate; break }
    }
}
if (-not $boardAddress) {
    throw 'Paired RK3588 board not found. Connect both devices to a reachable LAN and enable its MarsDog Avahi service.'
}
$firewallStatus = 'NOT_CHECKED'
if (-not $DiscoverOnly) {
    $needsUpdate = $true
    try {
        $rule = Get-NetFirewallRule -Name 'MarsDog-RemoteVisualization-ROS2-UDP' -ErrorAction Stop
        $remote = @($rule | Get-NetFirewallAddressFilter | Select-Object -ExpandProperty RemoteAddress)
        $ports = $rule | Get-NetFirewallPortFilter
        $needsUpdate = ($rule.Enabled -ne 'True' -or $rule.Action -ne 'Allow' -or
                        $remote.Count -ne 1 -or $remote[0] -ne $boardAddress -or
                        ($ports.LocalPort -join ',') -ne '17900-17971,28900-28971')
        if (Get-Command Get-NetFirewallHyperVRule -ErrorAction SilentlyContinue) {
            $hyper = Get-NetFirewallHyperVRule -Name 'MarsDog-RemoteVisualization-WSL-UDP' -ErrorAction Stop
            $remoteHyper = @($hyper.RemoteAddresses)
            $needsUpdate = ($needsUpdate -or -not $hyper.Enabled -or $hyper.Action -ne 'Allow' -or
                            $remoteHyper.Count -ne 1 -or $remoteHyper[0] -ne $boardAddress)
        }
    } catch { $needsUpdate = $true }
    if ($needsUpdate) {
        $firewallScript = Join-Path $PSScriptRoot 'configure-windows-firewall.ps1'
        $admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
            [Security.Principal.WindowsBuiltInRole]::Administrator)
        if ($admin) { & $firewallScript -BoardIP $boardAddress }
        else {
            # Only the existing narrow board rules are updated; Windows owns elevation.
            $arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $firewallScript + '" -BoardIP ' + $boardAddress
            $operation = Start-Process -FilePath powershell.exe -Verb RunAs -WindowStyle Hidden -PassThru -ArgumentList $arguments
            if (-not $operation.WaitForExit(60000)) { throw 'Firewall authorization has not completed. Retry after the Windows prompt.' }
            if ($operation.ExitCode -ne 0) { throw 'Windows firewall update failed or was cancelled.' }
        }
        $firewallStatus = 'UPDATED'
    } else { $firewallStatus = 'CURRENT' }
}
$result = @{ boardIP = $boardAddress; board_id = $identity.board_id; discovery = $source;
             firewall = $firewallStatus; localAddresses = $addresses; timestamp = (Get-Date).ToString('o') }
$result | ConvertTo-Json | Set-Content -LiteralPath $cacheFile -Encoding UTF8
$result | ConvertTo-Json -Compress
