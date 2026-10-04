param(
    [string]$IdentityFile = "$env:USERPROFILE\.ssh\game-support-demo_ed25519",
    [string]$KnownHostsFile = "$env:USERPROFILE\.ssh\game-support-demo_known_hosts",
    [string]$ServerAddress = '45.77.24.56',
    [string]$SshUser = 'root',
    [ValidateRange(1, 65535)][int]$LocalPort = 5175,
    [ValidateRange(1, 65535)][int]$RemotePort = 15175
)

$ErrorActionPreference = 'Stop'
$keyPath = (Resolve-Path -LiteralPath $IdentityFile).Path
$hostsPath = (Resolve-Path -LiteralPath $KnownHostsFile).Path
Get-Command ssh -ErrorAction Stop | Out-Null

Write-Host "Forwarding server localhost:$RemotePort to this PC localhost:$LocalPort."
Write-Host 'Keep this window open. Press Ctrl+C to stop. Docker is not started by this script.'
$sshArgs = @(
    '-N', '-T', '-i', $keyPath,
    '-o', "UserKnownHostsFile=$hostsPath",
    '-o', 'StrictHostKeyChecking=yes',
    '-o', 'BatchMode=yes',
    '-o', 'IdentitiesOnly=yes',
    '-o', 'ConnectTimeout=10',
    '-o', 'ExitOnForwardFailure=yes',
    '-o', 'ServerAliveInterval=20',
    '-o', 'ServerAliveCountMax=3',
    '-R', "127.0.0.1:${RemotePort}:127.0.0.1:${LocalPort}",
    "${SshUser}@${ServerAddress}"
)
while ($true) {
    & ssh @sshArgs
    Write-Warning "Tunnel disconnected (exit $LASTEXITCODE). Retrying in 10 seconds."
    Start-Sleep -Seconds 10
}
