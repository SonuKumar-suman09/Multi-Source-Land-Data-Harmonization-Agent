param(
    [string]$BackupRoot = "backups"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $backupPath = Join-Path $BackupRoot "landsync-$timestamp"
    New-Item -ItemType Directory -Path $backupPath -Force | Out-Null

    $storageBackend = "local"
    if (Test-Path ".env") {
        $storageLine = Get-Content ".env" | Where-Object { $_ -match '^\s*STORAGE_BACKEND\s*=' } | Select-Object -Last 1
        if ($storageLine) { $storageBackend = ($storageLine -split "=", 2)[1].Trim().Trim('"').Trim("'") }
    }

    & docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/landsync-backup.dump'
    if ($LASTEXITCODE -ne 0) { throw "PostgreSQL dump failed. Confirm docker compose services are running." }
    $dumpPath = Join-Path $backupPath "database.dump"
    & docker compose cp "db:/tmp/landsync-backup.dump" $dumpPath
    if ($LASTEXITCODE -ne 0) { throw "Could not copy the database dump from the db container." }
    & docker compose exec -T db rm -f /tmp/landsync-backup.dump

    $includedDirectories = @()
    foreach ($directory in @("uploads", "knowledge", "processed")) {
        $sourcePath = Join-Path $repoRoot "data/$directory"
        if (Test-Path $sourcePath) {
            $archiveName = "$directory.zip"
            Compress-Archive -Path $sourcePath -DestinationPath (Join-Path $backupPath $archiveName) -Force
            $includedDirectories += $directory
        }
    }

    $gitCommit = (& git rev-parse HEAD 2>$null).Trim()
    $manifest = [ordered]@{
        created_at = (Get-Date).ToUniversalTime().ToString("o")
        git_commit = $gitCommit
        storage_backend = $storageBackend
        database_dump = "database.dump"
        local_data_archives = $includedDirectories
        note = if ($storageBackend -eq "minio") { "MinIO object bytes are external; separately snapshot the configured bucket before relying on this backup." } else { "Database and local file directories are included." }
    }
    $manifest | ConvertTo-Json -Depth 4 | Set-Content -Path (Join-Path $backupPath "manifest.json") -Encoding UTF8
    Write-Host "Backup created: $backupPath"
    if ($storageBackend -eq "minio") { Write-Warning "MinIO object bytes are not included. Back up the MinIO bucket separately." }
}
finally {
    Pop-Location
}
