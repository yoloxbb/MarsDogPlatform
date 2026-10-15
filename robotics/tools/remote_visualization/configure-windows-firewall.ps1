#Requires -RunAsAdministrator
param([string]$BoardIP = '192.168.5.101')
$ErrorActionPreference = 'Stop'
$parsedAddress = [System.Net.IPAddress]::Parse($BoardIP)
if ($parsedAddress.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
    throw 'BoardIP must be an IPv4 address.'
}
$directory = Join-Path $env:LOCALAPPDATA 'MarsDog\remote-visualization'
New-Item -ItemType Directory -Path $directory -Force | Out-Null
$statusPath = Join-Path $directory 'windows-firewall-status.json'
$ports = @('17900-17971', '28900-28971') # ROS domains 42 and isolated verification 86.
$ruleName = 'MarsDog-RemoteVisualization-ROS2-UDP'
$hyperVName = 'MarsDog-RemoteVisualization-WSL-UDP'
$wslCreator = '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}'
try {
    $existing = Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue
    if ($existing) {
        $existing | Set-NetFirewallRule -Enabled True -Action Allow -Direction Inbound -Profile Any
        $existing | Get-NetFirewallAddressFilter | Set-NetFirewallAddressFilter -RemoteAddress $BoardIP
        $existing | Get-NetFirewallPortFilter | Set-NetFirewallPortFilter -Protocol UDP -LocalPort $ports
    } else {
        $parameters = @{ Name = $ruleName; DisplayName = 'MarsDog remote visualization: board ROS 2 UDP';
            Direction = 'Inbound'; Action = 'Allow'; Protocol = 'UDP'; LocalPort = $ports;
            RemoteAddress = $BoardIP; Profile = 'Any' }
        New-NetFirewallRule @parameters | Out-Null
    }
    if (Get-Command New-NetFirewallHyperVRule -ErrorAction SilentlyContinue) {
        $existingHyperV = Get-NetFirewallHyperVRule -Name $hyperVName -ErrorAction SilentlyContinue
        if ($existingHyperV) {
            $parameters = @{ Name = $hyperVName; Enabled = $true; Action = 'Allow';
                Protocol = 'UDP'; LocalPorts = $ports; RemoteAddresses = $BoardIP }
            Set-NetFirewallHyperVRule @parameters
        } else {
            $parameters = @{ Name = $hyperVName; DisplayName = 'MarsDog WSL: board ROS 2 UDP';
                Direction = 'Inbound'; VMCreatorId = $wslCreator; Protocol = 'UDP';
                LocalPorts = $ports; RemoteAddresses = $BoardIP; Action = 'Allow' }
            New-NetFirewallHyperVRule @parameters | Out-Null
        }
    }
    @{ status = 'APPLIED'; boardIP = $BoardIP; ports = $ports; timestamp = (Get-Date).ToString('o') } |
        ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding UTF8
} catch {
    @{ status = 'FAILED'; error = $_.Exception.Message; timestamp = (Get-Date).ToString('o') } |
        ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding UTF8
    throw
}
