# Apply or remove split-horizon DNS from dns-client.json using NRPT.
# Run as Administrator. Usage: .\dns-apply-windows.ps1 [path-to-dns-client.json]
# Default path: $env:USERPROFILE\.nebula\dns-client.json (or $env:NEBULA_OUTPUT_DIR\dns-client.json if set).
# To test: Resolve-DnsName host.nebula.example.com or ping (nslookup bypasses NRPT).

$ErrorActionPreference = "Stop"
$RuleName = "NebulaCommander"

$OutputDir = if ($env:NEBULA_OUTPUT_DIR) { $env:NEBULA_OUTPUT_DIR } else { Join-Path $env:USERPROFILE ".nebula" }
$ConfigPath = if ($args.Count -ge 1) { $args[0] } else { Join-Path $OutputDir "dns-client.json" }

# Remove every rule with this DisplayName (Remove-DnsClientNrptRule -Name; CIM delete does not work for NRPT)
$max = 10
for ($i = 0; $i -lt $max; $i++) {
  $names = @(Get-DnsClientNrptRule | Where-Object { $_.DisplayName -eq $RuleName } | ForEach-Object { $_.Name })
  if ($names.Count -eq 0) { break }
  foreach ($n in $names) { Remove-DnsClientNrptRule -Name $n -Confirm:$false -Force -ErrorAction SilentlyContinue }
}

if (-not (Test-Path -LiteralPath $ConfigPath)) {
    exit 0
}

$json = Get-Content -Raw -Path $ConfigPath | ConvertFrom-Json
$domain = $json.domain
$dnsServers = @($json.dns_servers)

if (-not $domain -or $dnsServers.Count -eq 0) {
    exit 0
}

$namespace = if ($domain.StartsWith(".")) { $domain } else { ".$domain" }
Add-DnsClientNrptRule -Namespace $namespace -DisplayName $RuleName -NameServers $dnsServers -Confirm:$false
