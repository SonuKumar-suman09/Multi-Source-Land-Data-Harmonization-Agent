param(
    [Parameter(Mandatory = $true)]
    [string]$BackupPath,
    [switch]$MinioBucketRestored
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    $resolvedBackup = (Resolve-Path -LiteralPath $BackupPath).Path
    $manifestPath = Join-Path $resolvedBackup "manifest.json"
    $dumpPath = Join-Path $resolvedBackup "database.dump"
    if (!(Test-Path -LiteralPath $manifestPath) -or !(Test-Path -LiteralPath $dumpPath)) {
        throw "Backup folder must contain manifest.json and database.dump."
    }

    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if ($manifest.storage_backend -eq "minio" -and !$MinioBucketRestored) {
        throw "This backup references MinIO. Restore the matching MinIO bucket separately, then rerun with -MinioBucketRestored."
    }
    foreach ($directory in @($manifest.local_data_archives)) {
        if ($directory -notin @("uploads", "knowledge", "processed")) {
            throw "Unexpected local data directory in backup manifest: $directory"
        }
        if (!(Test-Path -LiteralPath (Join-Path $resolvedBackup "$directory.zip"))) {
            throw "Backup is missing the declared archive $directory.zip."
        }
    }

    Write-Host "WARNING: restore replaces the current database and local uploads/knowledge/processed folders."
    $confirmation = Read-Host "Type RESTORE to continue"
    if ($confirmation -cne "RESTORE") {
        Write-Host "Restore cancelled."
        return
    }

    & docker compose stop api worker
    if ($LASTEXITCODE -ne 0) { throw "Could not stop API and worker services." }
    try {
        & docker compose cp $dumpPath "db:/tmp/landsync-restore.dump"
        if ($LASTEXITCODE -ne 0) { throw "Could not copy database dump into the db container." }
        $databaseUser = (& docker compose exec -T db printenv POSTGRES_USER).Trim()
        $databaseName = (& docker compose exec -T db printenv POSTGRES_DB).Trim()
        if ($LASTEXITCODE -ne 0 -or !$databaseUser -or !$databaseName) { throw "Could not read the configured database name and user from the db container." }
        & docker compose exec -T db pg_restore --clean --if-exists --no-owner -U $databaseUser -d $databaseName /tmp/landsync-restore.dump
        if ($LASTEXITCODE -ne 0) { throw "Database restore failed. Inspect the command output before restarting the app." }
        & docker compose exec -T db rm -f /tmp/landsync-restore.dump

        $dataRoot = Join-Path $repoRoot "data"
        New-Item -ItemType Directory -Path $dataRoot -Force | Out-Null
        foreach ($directory in @("uploads", "knowledge", "processed")) {
            $targetPath = Join-Path $dataRoot $directory
            $canonicalDataRoot = [System.IO.Path]::GetFullPath($dataRoot).TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
            $canonicalTarget = [System.IO.Path]::GetFullPath($targetPath)
            if (!$canonicalTarget.StartsWith($canonicalDataRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "Refusing to replace a path outside the repository data folder: $canonicalTarget"
            }
            if (Test-Path -LiteralPath $canonicalTarget) { Remove-Item -LiteralPath $canonicalTarget -Recurse -Force }
            $archivePath = Join-Path $resolvedBackup "$directory.zip"
            if (Test-Path -LiteralPath $archivePath) {
                Expand-Archive -LiteralPath $archivePath -DestinationPath $dataRoot -Force
            }
            else {
                New-Item -ItemType Directory -Path $targetPath -Force | Out-Null
            }
        }
    }
    finally {
        & docker compose start api worker
        if ($LASTEXITCODE -ne 0) { Write-Warning "API/worker could not be restarted automatically; check docker compose ps." }
    }

    Write-Host "Restore finished. Check http://localhost:8080 and http://127.0.0.1:8001/health/ready."
}
finally {
    Pop-Location
}
