param([string]$Path)
$errors = $null
[System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$null, [ref]$errors) | Out-Null
if ($errors -and $errors.Count -gt 0) {
  $errors | ForEach-Object { Write-Output ("ERR " + $_.Extent.StartLineNumber + ": " + $_.Message) }
  exit 1
}
Write-Output "PARSE_OK"
