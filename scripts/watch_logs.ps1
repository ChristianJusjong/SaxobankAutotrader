# Check if Railway CLI is installed
if (Get-Command "railway" -ErrorAction SilentlyContinue) {
    Write-Host "Starting Railway Log Stream..." -ForegroundColor Green
    railway logs
} else {
    Write-Host "Railway CLI is not installed or not in PATH." -ForegroundColor Red
    Write-Host "Please install it via npm: npm install -g @railway/cli" -ForegroundColor Yellow
    Write-Host "Or visit https://docs.railway.app/guides/cli for instructions." -ForegroundColor Yellow
    
    $choice = Read-Host "Do you want to attempt installation via npm now? (y/n)"
    if ($choice -eq 'y') {
        npm install -g @railway/cli
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Installation successful! Starting logs..." -ForegroundColor Green
            railway logs
        } else {
             Write-Host "Installation failed. Please install Node.js and npm first." -ForegroundColor Red
        }
    }
}
Pause
