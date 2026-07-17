# ============================================================================
# Laguna AI Line Balancing — Startup Script (PowerShell — Windows / macOS / Linux)
# ============================================================================
# Usage: .\scripts\start.ps1 [OPTION]
# Run with -Help for details.
# ============================================================================

param(
    [switch]$Dev,
    [switch]$Prod,
    [switch]$Build,
    [switch]$Down,
    [switch]$Clean,
    [switch]$Logs,
    [switch]$Status,
    [switch]$Local,
    [switch]$Migrate,
    [switch]$MakeMigrations,
    [switch]$Shell,
    [switch]$Superuser,
    [switch]$Test,
    [switch]$Backup,
    [string]$Restore,
    [switch]$Staged,
    [switch]$Fast,
    [switch]$Help
)

# ── Colours ─────────────────────────────────────────────────────────────────
$ErrorActionPreference = "Stop"

function Write-Colour($Message, $Colour = "White") {
    Write-Host $Message -ForegroundColor $Colour
}

# ── Project paths ───────────────────────────────────────────────────────────
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$BackendDir = Join-Path $ProjectRoot "backend"
$EnvFile = Join-Path $ProjectRoot ".env"

# ── Banner ──────────────────────────────────────────────────────────────────
function Show-Banner {
    Write-Host ""
    Write-Colour "  ======================================================" Cyan
    Write-Colour "       Laguna AI  —  Line Balancing Platform" Cyan
    Write-Colour "  ======================================================" Cyan
    Write-Host ""
}

# ── Help ────────────────────────────────────────────────────────────────────
function Show-Help {
    Show-Banner
    Write-Host "Usage: .\scripts\start.ps1 [OPTION]"
    Write-Host ""
    Write-Colour "Docker Commands:" White
    Write-Host "  -Dev              Start development services  (db + redis + backend + pgadmin)"
    Write-Host "  -Prod             Start production services   (db + redis + backend + celery + nginx)"
    Write-Host "  -Build            Rebuild Docker images and start dev services"
    Write-Host "  -Down             Stop and remove all containers"
    Write-Host "  -Clean            Stop containers and remove volumes (DATA LOSS!)"
    Write-Host "  -Logs             Tail logs for all running containers"
    Write-Host "  -Status           Show status of all containers"
    Write-Host ""
    Write-Colour "Local Development:" White
    Write-Host "  -Local            Start Django dev server locally (no Docker)"
    Write-Host "  -Migrate          Run database migrations"
    Write-Host "  -MakeMigrations   Create new migration files"
    Write-Host "  -Shell            Open Django interactive shell"
    Write-Host "  -Superuser        Create a Django superuser"
    Write-Host "  -Test             Run the test suite"
    Write-Host ""
    Write-Colour "Database:" White
    Write-Host "  -Backup           Backup PostgreSQL database to timestamped file"
    Write-Host '  -Restore "FILE"   Restore database from a backup file'
    Write-Host ""
    Write-Colour "Startup Modes (combine with Docker commands):" White
    Write-Host "  -Staged           Enable staged startup sequence  (default)"
    Write-Host "  -Fast             Disable staged startup (quick, parallel start)"
    Write-Host ""
    Write-Colour "Examples:" White
    Write-Host "  .\scripts\start.ps1 -Dev              # Start dev with Docker"
    Write-Host "  .\scripts\start.ps1 -Dev -Fast        # Quick-start dev"
    Write-Host "  .\scripts\start.ps1 -Local            # Run Django locally"
    Write-Host "  .\scripts\start.ps1 -Down             # Stop everything"
    Write-Host ""
}

# ── Load .env ───────────────────────────────────────────────────────────────
function Import-Env {
    if (Test-Path $EnvFile) {
        Write-Colour "[INFO] Loading environment from $EnvFile" Blue
        Get-Content $EnvFile | ForEach-Object {
            $line = $_.Trim()
            if ($line -and -not $line.StartsWith("#")) {
                $parts = $line -split "=", 2
                if ($parts.Count -eq 2) {
                    [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim(), "Process")
                }
            }
        }
    }
    elseif (Test-Path (Join-Path $ProjectRoot ".env.example")) {
        Write-Colour "[WARN] No .env file found. Copying .env.example -> .env" Yellow
        Copy-Item (Join-Path $ProjectRoot ".env.example") $EnvFile
        Import-Env
    }
    else {
        Write-Colour "[WARN] No .env file found. Using defaults." Yellow
    }
}

# ── Docker Compose command ──────────────────────────────────────────────────
function Get-DockerCompose {
    try {
        docker compose version 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { return "docker compose" }
    }
    catch {}

    try {
        $null = Get-Command docker-compose -ErrorAction Stop
        return "docker-compose"
    }
    catch {}

    Write-Colour "[ERROR] Docker Compose is not installed." Red
    exit 1
}

function Invoke-DC {
    param([string]$CommandArgs)
    $dc = Get-DockerCompose
    Invoke-Expression "$dc $CommandArgs"
}

# ── Check prerequisites ────────────────────────────────────────────────────
function Assert-Docker {
    try { $null = Get-Command docker -ErrorAction Stop } catch {
        Write-Colour "[ERROR] Docker is not installed." Red; exit 1
    }
    docker info 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Colour "[ERROR] Docker daemon is not running. Start Docker Desktop." Red; exit 1
    }
    Write-Colour "[OK] Docker is available" Green
}

function Assert-Python {
    try { $null = Get-Command python -ErrorAction Stop } catch {
        Write-Colour "[ERROR] Python is not installed or not in PATH." Red; exit 1
    }
    $ver = python --version 2>&1
    Write-Colour "[OK] $ver" Green
}

function Enable-Venv {
    $venvActivate = Join-Path $ProjectRoot ".venv\Scripts\Activate.ps1"
    if (Test-Path $venvActivate) {
        Write-Colour "[INFO] Activating virtual environment..." Blue
        & $venvActivate
    }
    else {
        Write-Colour "[WARN] No .venv found. Using system Python." Yellow
    }
}

# ════════════════════════════════════════════════════════════════════════════
# DOCKER COMMANDS
# ════════════════════════════════════════════════════════════════════════════

function Start-DevStaged {
    Write-Colour "[INFO] Starting dev services (staged sequence)..." Blue

    Write-Colour "  Stage 1/4: Core infrastructure (db, redis)..." Cyan
    Invoke-DC "-f docker-compose.yml -f docker-compose.override.yml up -d db redis"
    Write-Host "  Waiting for databases to be healthy..."
    Start-Sleep -Seconds 8

    Write-Colour "  Stage 2/4: Backend application..." Cyan
    Invoke-DC "-f docker-compose.yml -f docker-compose.override.yml up -d backend"
    Start-Sleep -Seconds 5

    Write-Colour "  Stage 3/4: Developer tools (pgadmin)..." Cyan
    Invoke-DC "-f docker-compose.yml -f docker-compose.override.yml up -d pgadmin"

    Write-Colour "  Stage 4/4: Reverse proxy (nginx)..." Cyan
    Invoke-DC "up -d nginx"

    Write-Colour "[OK] All dev services started" Green
}

function Start-DevFast {
    Write-Colour "[INFO] Starting dev services (fast mode)..." Blue
    Invoke-DC "-f docker-compose.yml -f docker-compose.override.yml up --force-recreate -d"
    Invoke-DC "up -d nginx"
    Write-Colour "[OK] All dev services started" Green
}

function Start-ProdStaged {
    Write-Colour "[INFO] Starting production services (staged sequence)..." Blue

    Write-Colour "  Stage 1/4: Core infrastructure (db, redis)..." Cyan
    Invoke-DC "-f docker-compose.yml -f docker-compose.prod.yml up -d db redis"
    Start-Sleep -Seconds 10

    Write-Colour "  Stage 2/4: Backend application (gunicorn)..." Cyan
    Invoke-DC "-f docker-compose.yml -f docker-compose.prod.yml up -d backend"
    Start-Sleep -Seconds 8

    Write-Colour "  Stage 3/4: Background workers (celery)..." Cyan
    Invoke-DC "-f docker-compose.yml -f docker-compose.prod.yml up -d celery"
    Start-Sleep -Seconds 5

    Write-Colour "  Stage 4/4: Reverse proxy (nginx)..." Cyan
    Invoke-DC "-f docker-compose.yml -f docker-compose.prod.yml up -d nginx"

    Write-Colour "[OK] All production services started" Green
}

function Start-ProdFast {
    Write-Colour "[INFO] Starting production services (fast mode)..." Blue
    Invoke-DC "-f docker-compose.yml -f docker-compose.prod.yml up --force-recreate -d"
    Write-Colour "[OK] All production services started" Green
}

# ════════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════════

$StagedMode = -not $Fast

# No flags provided => show help
$anyCommand = $Dev -or $Prod -or $Build -or $Down -or $Clean -or $Logs -or $Status `
    -or $Local -or $Migrate -or $MakeMigrations -or $Shell -or $Superuser `
    -or $Test -or $Backup -or ($Restore -ne "") -or $Help

if (-not $anyCommand) {
    Show-Help
    exit 0
}

if ($Help) { Show-Help; exit 0 }

Show-Banner
Import-Env

$env:COMPOSE_FILE = "docker-compose.yml"

# ── Docker commands ─────────────────────────────────────────────────────────

if ($Dev) {
    Assert-Docker
    if ($StagedMode) { Start-DevStaged } else { Start-DevFast }
    Write-Host ""
    Invoke-DC "ps -a"
    Write-Host ""
    $port = if ($env:BACKEND_PORT) { $env:BACKEND_PORT } else { "8000" }
    $pgport = if ($env:PGADMIN_PORT) { $env:PGADMIN_PORT } else { "5050" }
    Write-Colour "  Backend:  http://localhost:$port" Green
    Write-Colour "  Swagger:  http://localhost:$port/swagger/" Green
    Write-Colour "  pgAdmin:  http://localhost:$pgport" Green
    Write-Colour "  Redis UI: http://localhost:8082" Green
    Write-Colour "  Grafana:  http://localhost:4000" Green
    Write-Host ""
}

if ($Prod) {
    Assert-Docker
    if ($StagedMode) { Start-ProdStaged } else { Start-ProdFast }
    Write-Host ""
    Invoke-DC "ps -a"
    Write-Host ""
    Write-Colour "  Application: http://localhost (via nginx)" Green
    Write-Host ""
}

if ($Build) {
    Assert-Docker
    Write-Colour "[INFO] Rebuilding Docker images..." Blue
    Invoke-DC "build --no-cache"
    Write-Colour "[OK] Images rebuilt" Green
    if ($StagedMode) { Start-DevStaged } else { Start-DevFast }
    Invoke-DC "ps -a"
}

if ($Down) {
    Assert-Docker
    Write-Colour "[INFO] Stopping and removing all containers..." Blue
    Invoke-DC "-f docker-compose.yml -f docker-compose.override.yml -f docker-compose.prod.yml down"
    Write-Colour "[OK] All containers stopped and removed" Green
}

if ($Clean) {
    Assert-Docker
    Write-Colour "[WARNING] This will remove all containers AND volumes (database data will be lost!)" Red
    $confirm = Read-Host "Continue? (y/N)"
    if ($confirm -eq "y") {
        Invoke-DC "-f docker-compose.yml -f docker-compose.override.yml -f docker-compose.prod.yml down -v"
        Write-Colour "[OK] Containers and volumes removed" Green
    }
    else {
        Write-Host "  Cancelled."
    }
}

if ($Logs) { Invoke-DC "logs -f" }
if ($Status) { Invoke-DC "ps -a" }

if ($Backup) {
    $dbUser = if ($env:DB_USER) { $env:DB_USER } else { "postgres" }
    $dbName = if ($env:DB_NAME) { $env:DB_NAME } else { "Laguna" }
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $backupFile = Join-Path $ProjectRoot "backup_$timestamp.sql"
    Write-Colour "[INFO] Backing up database..." Blue
    Invoke-DC "exec -T db pg_dump -U $dbUser $dbName" | Out-File -FilePath $backupFile -Encoding utf8
    Write-Colour "[OK] Backup saved to $backupFile" Green
}

if ($Restore -ne "") {
    if (-not (Test-Path $Restore)) {
        Write-Colour "[ERROR] File not found: $Restore" Red; exit 1
    }
    $dbUser = if ($env:DB_USER) { $env:DB_USER } else { "postgres" }
    $dbName = if ($env:DB_NAME) { $env:DB_NAME } else { "Laguna" }
    Write-Colour "[INFO] Restoring database from $Restore..." Blue
    Get-Content $Restore | Invoke-DC "exec -T db psql -U $dbUser $dbName"
    Write-Colour "[OK] Database restored" Green
}

# ── Local commands ──────────────────────────────────────────────────────────

if ($Local) {
    Assert-Python
    Activate-Venv
    Write-Colour "[INFO] Starting Django development server..." Blue
    Write-Host "  Backend dir: $BackendDir"
    Write-Host ""
    Write-Colour "  Server:   http://127.0.0.1:8000" Green
    Write-Colour "  Swagger:  http://127.0.0.1:8000/swagger/" Green
    Write-Colour "  Redoc:    http://127.0.0.1:8000/redoc/" Green
    Write-Host ""
    Push-Location $BackendDir
    python manage.py runserver
    Pop-Location
}

if ($Migrate) {
    Assert-Python; Enable-Venv
    Write-Colour "[INFO] Running database migrations..." Blue
    Push-Location $BackendDir
    python manage.py migrate
    Pop-Location
    Write-Colour "[OK] Migrations applied" Green
}

if ($MakeMigrations) {
    Assert-Python; Enable-Venv
    Write-Colour "[INFO] Creating migration files..." Blue
    Push-Location $BackendDir
    python manage.py makemigrations
    Pop-Location
    Write-Colour "[OK] Migration files created" Green
}

if ($Shell) {
    Assert-Python; Enable-Venv
    Push-Location $BackendDir
    python manage.py shell
    Pop-Location
}

if ($Superuser) {
    Assert-Python; Enable-Venv
    Push-Location $BackendDir
    python manage.py createsuperuser
    Pop-Location
}

if ($Test) {
    Assert-Python; Enable-Venv
    if ($Test) {
        Assert-Python; Activate-Venv
        if ( $Test) {
            Assert-Python; Activate-Venv
            Write-Colour "[INFO] Running test suite..." Blue
            Push-Location $BackendDir
            python manage.py test
            Pop-Location
            Write-Colour "[OK] Tests complete" Green
        }
    }
}