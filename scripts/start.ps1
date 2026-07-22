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
        Write-Colour "[WARN] No .env file found. Copying .env.example to .env" Yellow
        Copy-Item (Join-Path $ProjectRoot ".env.example") $EnvFile
        Import-Env
    }
    else {
        Write-Colour "[WARN] No .env file found. Using defaults." Yellow
    }
}

# ── Assertions ──────────────────────────────────────────────────────────────
function Assert-Docker {
    try {
        $null = Get-Command docker -ErrorAction Stop
        $dockerInfo = docker info 2>&1
        if ($LASTEXITCODE -ne 0 -or $dockerInfo -match "error during connect") {
            Write-Colour "[ERROR] Docker daemon is not running. Please start Docker Desktop." Red
            exit 1
        }
        Write-Colour "[OK] Docker is available" Green
    }
    catch {
        Write-Colour "[ERROR] Docker is not installed or not in PATH." Red
        exit 1
    }
}

function Invoke-DC($ArgsList) {
    if (Get-Command "docker-compose" -ErrorAction SilentlyContinue) {
        Invoke-Expression "docker-compose $ArgsList"
    } else {
        Invoke-Expression "docker compose $ArgsList"
    }
}

function Assert-Python {
    try {
        $null = Get-Command python -ErrorAction Stop
    }
    catch {
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

function Start-AllStaged {
    Write-Colour "[INFO] Starting ALL services (staged sequence)..." Blue

    Write-Colour "  Stage 1/4: Core infrastructure (db, redis)..." Cyan
    Invoke-DC "-f docker-compose.yml -f docker-compose.override.yml -f docker-compose.prod.yml up -d db redis"
    Write-Host "  Waiting for databases to be healthy..."
    Start-Sleep -Seconds 10

    Write-Colour "  Stage 2/4: Backend application..." Cyan
    Invoke-DC "-f docker-compose.yml -f docker-compose.override.yml -f docker-compose.prod.yml up -d backend"
    Start-Sleep -Seconds 5

    Write-Colour "  Stage 3/4: Background workers (celery, scheduler)..." Cyan
    Invoke-DC "-f docker-compose.yml -f docker-compose.prod.yml up -d celery scheduler"
    Start-Sleep -Seconds 3

    Write-Colour "  Stage 4/4: Developer tools and reverse proxy (pgadmin, nginx)..." Cyan
    Invoke-DC "-f docker-compose.yml -f docker-compose.override.yml up -d pgadmin"
    Invoke-DC "-f docker-compose.yml -f docker-compose.prod.yml up -d nginx"

    Write-Colour "[OK] All services started" Green
}

function Start-AllFast {
    Write-Colour "[INFO] Starting ALL services (fast mode)..." Blue
    Invoke-DC "-f docker-compose.yml -f docker-compose.override.yml -f docker-compose.prod.yml up --force-recreate -d"
    Write-Colour "[OK] All services started" Green
}


function Start-DevStaged {
    Write-Colour "[INFO] Starting dev services (staged sequence)..." Blue
    Write-Colour "  Stage 1/3: Core infrastructure (db, redis)..." Cyan
    Invoke-DC "-f docker-compose.yml -f docker-compose.override.yml up -d db redis"
    Start-Sleep -Seconds 8
    Write-Colour "  Stage 2/3: Backend application..." Cyan
    Invoke-DC "-f docker-compose.yml -f docker-compose.override.yml up -d backend"
    Start-Sleep -Seconds 5
    Write-Colour "  Stage 3/3: Developer tools (pgadmin)..." Cyan
    Invoke-DC "-f docker-compose.yml -f docker-compose.override.yml up -d pgadmin"
    Write-Colour "[OK] All dev services started" Green
}

function Start-DevFast {
    Write-Colour "[INFO] Starting dev services (fast mode)..." Blue
    Invoke-DC "-f docker-compose.yml -f docker-compose.override.yml up --force-recreate -d"
    Write-Colour "[OK] All dev services started" Green
}

function Start-ProdStaged {
    Write-Colour "[INFO] Starting production services (staged sequence)..." Blue
    Write-Colour "  Stage 1/3: Core infrastructure (db, redis)..." Cyan
    Invoke-DC "-f docker-compose.yml -f docker-compose.prod.yml up -d db redis"
    Start-Sleep -Seconds 10
    Write-Colour "  Stage 2/3: Application and workers..." Cyan
    Invoke-DC "-f docker-compose.yml -f docker-compose.prod.yml up -d backend celery scheduler"
    Start-Sleep -Seconds 8
    Write-Colour "  Stage 3/3: Reverse proxy (nginx)..." Cyan
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

# No flags provided => start ALL
$anyCommand = $Dev -or $Prod -or $Build -or $Down -or $Clean -or $Logs -or $Status `
    -or $Local -or $Migrate -or $MakeMigrations -or $Shell -or $Superuser `
    -or $Test -or $Backup -or ($Restore -ne "") -or $Help

if ($Help) { Show-Help; exit 0 }

Show-Banner
Import-Env

$env:COMPOSE_FILE = "docker-compose.yml"

# ── Docker commands ─────────────────────────────────────────────────────────

if (-not $anyCommand) {
    Assert-Docker
    if ($StagedMode) { Start-AllStaged } else { Start-AllFast }
    
    $bp = if ($env:BACKEND_PORT) { $env:BACKEND_PORT } else { "8000" }
    $pp = if ($env:PGADMIN_PORT) { $env:PGADMIN_PORT } else { "5050" }
    Write-Host "  Dev Backend:   http://localhost:$bp"
    Write-Host "  Swagger:       http://localhost:$bp/swagger/"
    Write-Host "  pgAdmin:       http://localhost:$pp"
    Write-Host "  Redis UI:      http://localhost:8082"
    Write-Host "  Prod (nginx):  http://localhost"
    Write-Host "  Grafana:       http://localhost:4000"
    Write-Host ""
    exit 0
}

if ($Dev) {
    Assert-Docker
    if ($StagedMode) { Start-DevStaged } else { Start-DevFast }
    
    $bp = if ($env:BACKEND_PORT) { $env:BACKEND_PORT } else { "8000" }
    $pp = if ($env:PGADMIN_PORT) { $env:PGADMIN_PORT } else { "5050" }
    Write-Host "  Dev Backend:   http://localhost:$bp"
    Write-Host "  Swagger:       http://localhost:$bp/swagger/"
    Write-Host "  pgAdmin:       http://localhost:$pp"
    Write-Host "  Redis UI:      http://localhost:8082"
    Write-Host "  Grafana:       http://localhost:4000"
    Write-Host ""
}

if ($Prod) {
    Assert-Docker
    if ($StagedMode) { Start-ProdStaged } else { Start-ProdFast }
    Write-Host "  Prod (nginx):  http://localhost"
    Write-Host "  Grafana:       http://localhost:4000"
    Write-Host ""
}

if ($Build) {
    Assert-Docker
    Write-Colour "[INFO] Rebuilding Docker images and starting dev services..." Blue
    Invoke-DC "-f docker-compose.yml -f docker-compose.override.yml down"
    Invoke-DC "-f docker-compose.yml -f docker-compose.override.yml build"
    Invoke-DC "-f docker-compose.yml -f docker-compose.override.yml up -d"
    Write-Colour "[OK] Rebuild complete" Green
}

if ($Down) {
    Assert-Docker
    Write-Colour "[INFO] Stopping and removing containers..." Blue
    Invoke-DC "-f docker-compose.yml -f docker-compose.override.yml -f docker-compose.prod.yml down"
    Write-Colour "[OK] Containers stopped" Green
}

if ($Clean) {
    Assert-Docker
    Write-Colour "[WARN] Destructive action initiated. This will delete all containers and volumes." Yellow
    $confirm = Read-Host "Are you sure you want to continue? (y/N)"
    if ($confirm -match "^[yY](es)?$") {
        Invoke-DC "-f docker-compose.yml -f docker-compose.override.yml -f docker-compose.prod.yml down -v"
        Write-Colour "[OK] Cleaned all containers and volumes" Green
    } else {
        Write-Colour "[INFO] Aborted" Blue
    }
}

if ($Logs) {
    Assert-Docker
    Invoke-DC "-f docker-compose.yml -f docker-compose.override.yml -f docker-compose.prod.yml logs -f"
}

if ($Status) {
    Assert-Docker
    Invoke-DC "-f docker-compose.yml -f docker-compose.override.yml -f docker-compose.prod.yml ps"
}

# ── Local commands (Python) ─────────────────────────────────────────────────

$requiresPython = $Local -or $Migrate -or $MakeMigrations -or $Shell -or $Superuser -or $Test
if ($requiresPython) {
    Assert-Python
    Enable-Venv
    Set-Location $BackendDir
}

if ($Local) {
    Write-Colour "[INFO] Starting local Django dev server..." Blue
    python manage.py runserver
}

if ($Migrate) {
    Write-Colour "[INFO] Running database migrations..." Blue
    python manage.py migrate
}

if ($MakeMigrations) {
    Write-Colour "[INFO] Creating migration files..." Blue
    python manage.py makemigrations
}

if ($Shell) {
    python manage.py shell
}

if ($Superuser) {
    Write-Colour "[INFO] Creating superuser..." Blue
    python manage.py createsuperuser
}

if ($Test) {
    Write-Colour "[INFO] Running test suite..." Blue
    pytest --cov=. --cov-report=term-missing
}

if ($Backup) {
    Assert-Docker
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $backupFile = Join-Path $ProjectRoot "backup_$timestamp.sql"
    $dbUser = if ($env:DB_USER) { $env:DB_USER } else { "postgres" }
    $dbName = if ($env:DB_NAME) { $env:DB_NAME } else { "Laguna" }
    Write-Colour "[INFO] Backing up database..." Blue
    Set-Location $ProjectRoot
    Invoke-DC "exec -T db pg_dump -U $dbUser $dbName > `"$backupFile`""
    Write-Colour "[OK] Backup saved to $backupFile" Green
}

if ($Restore) {
    Assert-Docker
    if (-not (Test-Path $Restore)) {
        Write-Colour "[ERROR] File not found: $Restore" Red
        exit 1
    }
    $dbUser = if ($env:DB_USER) { $env:DB_USER } else { "postgres" }
    $dbName = if ($env:DB_NAME) { $env:DB_NAME } else { "Laguna" }
    Write-Colour "[INFO] Restoring database from $Restore..." Blue
    Set-Location $ProjectRoot
    Invoke-DC "exec -T db psql -U $dbUser $dbName < `"$Restore`""
    Write-Colour "[OK] Database restored." Green
}