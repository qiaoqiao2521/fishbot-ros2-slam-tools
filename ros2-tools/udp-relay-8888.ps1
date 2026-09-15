param(
  [Parameter(Mandatory = $true)][string]$WslIp,
  [int]$Port = 8888
)

$ErrorActionPreference = "Stop"

$wslAddr = [System.Net.IPAddress]::Parse($WslIp)
$listen = New-Object System.Net.Sockets.UdpClient($Port) # binds 0.0.0.0:$Port
$listen.Client.ReceiveBufferSize = 4MB

$wslEp = New-Object System.Net.IPEndPoint($wslAddr, $Port)
$lastClient = $null

Write-Host ("[relay] 0.0.0.0:{0} <-> {1}:{0}  (Ctrl+C to stop)" -f $Port, $WslIp)

try {
  while ($true) {
    $remote = New-Object System.Net.IPEndPoint([System.Net.IPAddress]::Any, 0)
    $data = $listen.Receive([ref]$remote)

    $fromWsl = $remote.Address.Equals($wslAddr) # treat any packet from WslIp as "from WSL"

    if ($fromWsl) {
      if ($null -ne $lastClient) {
        [void]$listen.Send($data, $data.Length, $lastClient)
        Write-Host ("[wsl->cli] {0}B to {1}:{2}" -f $data.Length, $lastClient.Address, $lastClient.Port)
      } else {
        Write-Host ("[wsl->cli] {0}B (no client yet)" -f $data.Length)
      }
    } else {
      $lastClient = $remote
      [void]$listen.Send($data, $data.Length, $wslEp)
      Write-Host ("[cli->wsl] {0}B from {1}:{2}" -f $data.Length, $remote.Address, $remote.Port)
    }
  }
}
finally {
  $listen.Close()
}

