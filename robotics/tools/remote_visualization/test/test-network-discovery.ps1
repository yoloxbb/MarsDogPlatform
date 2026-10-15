# Pure DNS parser and identity matching regression, with no network requests.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\network-discovery.ps1')
$id = 'a' * 64
function New-Record([string]$Service, [string]$ID) {
    $bytes = New-Object 'Collections.Generic.List[byte]'
    $bytes.AddRange([byte[]]@(0,0,132,0,0,0,0,1,0,0,0,0))
    foreach ($label in $Service.Split('.')) {
        $text = [Text.Encoding]::ASCII.GetBytes($label)
        $bytes.Add([byte]$text.Length); $bytes.AddRange([byte[]]$text)
    }
    $bytes.Add(0)
    $value = [Text.Encoding]::ASCII.GetBytes('board_id=' + $ID)
    $bytes.AddRange([byte[]]@(0,16,128,1,0,0,0,120,0,($value.Length+1),$value.Length))
    $bytes.AddRange([byte[]]$value)
    return ,$bytes.ToArray()
}
$service = 'MarsDog-RK3588-test._marsdog-ros2._tcp.local'
$valid = New-Record $service $id
if (-not [MarsDog.MdnsDiscovery]::Matches($valid,$id)) { throw 'Valid identity rejected' }
if ([MarsDog.MdnsDiscovery]::Matches($valid,('b' * 64))) { throw 'Wrong identity accepted' }
if ([MarsDog.MdnsDiscovery]::Matches((New-Record 'unrelated._ssh._tcp.local' $id),$id)) { throw 'Unrelated service accepted' }
$query = [byte[]]$valid.Clone(); $query[2] = 0; $query[3] = 0
if ([MarsDog.MdnsDiscovery]::Matches($query,$id)) { throw 'DNS query accepted as announcement' }
$truncated = [byte[]]$valid[0..($valid.Length-3)]
$rejected = $false
try { [MarsDog.MdnsDiscovery]::Matches($truncated,$id) | Out-Null } catch { $rejected = $true }
if (-not $rejected) { throw 'Truncated packet accepted' }
$cycle = [byte[]]@(0,0,132,0,0,0,0,1,0,0,0,0,192,12,0,16,0,1,0,0,0,0,0,0)
$rejected = $false
try { [MarsDog.MdnsDiscovery]::Matches($cycle,$id) | Out-Null } catch { $rejected = $true }
if (-not $rejected) { throw 'Compression pointer cycle accepted' }
'PASS: six offline DNS parser/identity cases'
