# ═══════════════════════════════════════════════════════════
# ESP32 FIRMWARE UPLOAD SCRIPT
# ═══════════════════════════════════════════════════════════

Write-Host "╔════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║      ESP32 FIRMWARE UPLOAD & SERIAL DATA TOOL         ║" -ForegroundColor Cyan
Write-Host "╚════════════════════════════════════════════════════════╝" -ForegroundColor Cyan

# Activate venv
&"C:\Users\ranan\Desktop\ANS\.venv\Scripts\Activate.ps1"

$port = "COM3"
$baud = 115200

Write-Host "`n[STEP 1] Checking ESP32 connection..." -ForegroundColor Yellow

# Try to connect
$test = python -m esptool -p $port read_mac 2>&1
if ($test -match "MAC") {
    Write-Host "✓ ESP32 found on $port" -ForegroundColor Green
} else {
    Write-Host "✗ ESP32 NOT FOUND - Check USB connection!" -ForegroundColor Red
    Write-Host "   - Try unplugging and replugging USB cable" -ForegroundColor Yellow
    Write-Host "   - Check Device Manager for COM ports" -ForegroundColor Yellow
    exit 1
}

Write-Host "`n[STEP 2] Erasing flash memory..." -ForegroundColor Yellow
python -m esptool -p $port erase-flash
if ($LASTEXITCODE -ne 0) {
    Write-Host "✗ Erase failed!" -ForegroundColor Red
    exit 1
}
Write-Host "✓ Flash erased" -ForegroundColor Green

Write-Host "`n[STEP 3] Upload firmware via Arduino IDE" -ForegroundColor Yellow
Write-Host "   - Open Arduino IDE" -ForegroundColor Cyan
Write-Host "   - File → Open → final_year_esp32_code.ino" -ForegroundColor Cyan
Write-Host "   - Select: Board 'ESP32 Dev Module', Port 'COM3'" -ForegroundColor Cyan
Write-Host "   - Sketch → Upload (Ctrl+U)" -ForegroundColor Cyan
Write-Host "`n⏳ Waiting for upload to complete..." -ForegroundColor Yellow
Read-Host "Press ENTER when upload is done in Arduino IDE"

Write-Host "`n[STEP 4] Testing serial connection..." -ForegroundColor Yellow
python test_serial_raw.py

Write-Host "`n✓ DONE!" -ForegroundColor Green
