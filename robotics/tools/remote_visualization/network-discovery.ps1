# DNS-SD discovery for the paired MarsDog board. No credentials or ROS commands.
if (-not ('MarsDog.MdnsDiscovery' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
namespace MarsDog {
 public static class MdnsDiscovery {
  static int U16(byte[] p, int at) {
   if(at<0 || at+2>p.Length) throw new ArgumentException("truncated DNS field");
   return (p[at]<<8)|p[at+1];
  }
  static string Name(byte[] p, ref int at) {
   int pos=at, end=-1; var labels=new List<string>(); var seen=new HashSet<int>();
   for(int hops=0; hops<64; hops++) {
    if(pos<0 || pos>=p.Length || !seen.Add(pos)) throw new ArgumentException("invalid DNS pointer");
    int len=p[pos++];
    if(len==0) { at=end<0?pos:end; return string.Join(".",labels); }
    if((len&192)==192) {
     if(pos>=p.Length) throw new ArgumentException("truncated DNS pointer");
     int pointer=((len&63)<<8)|p[pos++]; if(end<0) end=pos; pos=pointer; continue;
    }
    if(len>63 || pos+len>p.Length) throw new ArgumentException("invalid DNS label");
    labels.Add(Encoding.UTF8.GetString(p,pos,len)); pos+=len;
   }
   throw new ArgumentException("too many DNS pointers");
  }
  public static bool Matches(byte[] p, string id) {
   if(p.Length<12 || (U16(p,2)&32768)==0) return false;
   int questions=U16(p,4), records=U16(p,6)+U16(p,8)+U16(p,10), at=12;
   if(questions>64 || records>512) throw new ArgumentException("excessive DNS records");
   for(int i=0;i<questions;i++){Name(p,ref at);at+=4; if(at>p.Length) throw new ArgumentException("truncated question");}
   for(int i=0;i<records;i++){
    string name=Name(p,ref at); int type=U16(p,at), length=U16(p,at+8); at+=10;
    if(at+length>p.Length) throw new ArgumentException("truncated DNS record");
    if(type==16 && name.EndsWith("._marsdog-ros2._tcp.local",StringComparison.OrdinalIgnoreCase)){
     int end=at+length, pos=at;
     while(pos<end){int count=p[pos++];if(pos+count>end) throw new ArgumentException("truncated TXT");
      string value=Encoding.UTF8.GetString(p,pos,count);pos+=count;
      if(value=="board_id="+id) return true;
     }
    }
    at+=length;
   }
   return false;
  }
  static byte[] Query(string instance) {
   var bytes=new List<byte>(new byte[]{0,0,0,0,0,1,0,0,0,0,0,0});
   foreach(string label in (instance+"._marsdog-ros2._tcp.local").Split('.')){
    byte[] b=Encoding.UTF8.GetBytes(label); if(b.Length>63) throw new ArgumentException("DNS label too long");
    bytes.Add((byte)b.Length);bytes.AddRange(b);
   }
   bytes.AddRange(new byte[]{0,0,16,128,1}); return bytes.ToArray();
  }
  public static string[] Discover(string[] localAddresses,string instance,string id,int seconds) {
   var sockets=new List<UdpClient>();var found=new HashSet<string>();byte[] query=Query(instance);
   try {
    foreach(string address in localAddresses){
     UdpClient socket=null;
     try{
      IPAddress local=IPAddress.Parse(address);socket=new UdpClient(new IPEndPoint(local,0));
      socket.Client.SetSocketOption(SocketOptionLevel.IP,SocketOptionName.MulticastInterface,local.GetAddressBytes());
      socket.Client.SetSocketOption(SocketOptionLevel.IP,SocketOptionName.MulticastTimeToLive,255);
      socket.Client.Blocking=false;socket.Send(query,query.Length,new IPEndPoint(IPAddress.Parse("224.0.0.251"),5353));sockets.Add(socket);
     }catch(SocketException){if(socket!=null)socket.Close();}
    }
    DateTime deadline=DateTime.UtcNow.AddSeconds(seconds), nextSend=DateTime.UtcNow.AddSeconds(1);
    while(DateTime.UtcNow<deadline){
     foreach(UdpClient socket in sockets){
      while(socket.Available>0){
       IPEndPoint remote=new IPEndPoint(IPAddress.Any,0);byte[] packet=socket.Receive(ref remote);
       try{if(Matches(packet,id))found.Add(remote.Address.ToString());}catch(ArgumentException){}
      }
     }
     if(found.Count>0)break;
     if(DateTime.UtcNow>=nextSend){foreach(UdpClient socket in sockets)socket.Send(query,query.Length,new IPEndPoint(IPAddress.Parse("224.0.0.251"),5353));nextSend=DateTime.UtcNow.AddSeconds(1);}
     Thread.Sleep(25);
    }
    var result=new string[found.Count];found.CopyTo(result);return result;
   }finally{foreach(UdpClient socket in sockets)socket.Close();}
  }
 }
}
'@
}

function Get-MarsDogLocalIPv4 {
    $interfaces = @(Get-NetIPConfiguration | Where-Object {
        $_.IPv4Address -and $_.NetAdapter.Status -eq 'Up' -and $_.IPv4DefaultGateway
    })
    if ($interfaces.Count -eq 0) {
        $interfaces = @(Get-NetIPConfiguration | Where-Object {
            $_.IPv4Address -and $_.NetAdapter.Status -eq 'Up' -and $_.NetAdapter.HardwareInterface
        })
    }
    foreach ($adapter in $interfaces) {
        foreach ($address in $adapter.IPv4Address) {
            if ($address.IPAddress -notmatch '^(127\.|169\.254\.)') { $address.IPAddress }
        }
    }
}

function Test-MarsDogHostKey {
    param([string]$IPAddress, $Identity)
    $address = $null
    if (-not [Net.IPAddress]::TryParse($IPAddress, [ref]$address) -or
        $address.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or
        [Net.IPAddress]::IsLoopback($address)) { return $false }
    if ($Identity.board_id -notmatch '^[0-9a-f]{64}$') { return $false }
    $pinDirectory = Join-Path $env:LOCALAPPDATA 'MarsDog\remote-visualization'
    New-Item -ItemType Directory -Path $pinDirectory -Force | Out-Null
    $pinFile = Join-Path $pinDirectory ('known-hosts-' + $Identity.board_id)
    $alias = 'marsdog-' + $Identity.board_id
    [IO.File]::WriteAllText($pinFile, $alias + ' ' + $Identity.ssh_key_type + ' ' +
        $Identity.ssh_key_data + [Environment]::NewLine, (New-Object Text.UTF8Encoding($false)))
    # Windows ssh-keyscan has an incompatible KEX in the installed build.
    # The normal SSH client verifies the pinned key and runs only `true`.
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = (Get-Command ssh.exe -ErrorAction Stop).Source
    $info.Arguments = '-n -o BatchMode=yes -o ConnectTimeout=3 -o ConnectionAttempts=1' +
        ' -o StrictHostKeyChecking=yes -o CheckHostIP=no -o GlobalKnownHostsFile=none' +
        ' -o HostKeyAlgorithms=ssh-ed25519 -o HostKeyAlias=' + $alias +
        ' -o "UserKnownHostsFile=' + $pinFile + '" marsdog@' + $address.IPAddressToString + ' true'
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $process = [Diagnostics.Process]::Start($info)
    try {
        if (-not $process.WaitForExit(6500)) { $process.Kill(); $process.WaitForExit(); return $false }
        return $process.ExitCode -eq 0
    } finally { $process.Dispose() }
}
