# ViraClip Frontend Setup Script
# Ejecuta: .\setup.ps1

Write-Host "🚀 ViraClip Frontend Setup" -ForegroundColor Cyan
Write-Host ""

# Check if .env.local exists
if (-Not (Test-Path ".env.local")) {
    Write-Host "⚠️  .env.local no encontrado. Creando plantilla..." -ForegroundColor Yellow
    
    $envContent = @"
# Database (usa el mismo PostgreSQL del backend)
DATABASE_URL="postgresql://viraclip:viraclip_password@localhost:5432/viraclip?schema=public"

# Better Auth
BETTER_AUTH_SECRET="$(Get-Random -Count 32 | ForEach-Object { [char](Get-Random -Minimum 48 -Maximum 122) } | Join-String)"
BETTER_AUTH_URL="http://localhost:3000"

# Google OAuth (opcional - dejar vacío para empezar)
GOOGLE_CLIENT_ID=""
GOOGLE_CLIENT_SECRET=""

# Backend API
NEXT_PUBLIC_API_URL="http://localhost:8000"
"@
    
    $envContent | Out-File -FilePath ".env.local" -Encoding UTF8
    Write-Host "✅ .env.local creado. Revisa y edita si es necesario." -ForegroundColor Green
} else {
    Write-Host "✅ .env.local ya existe." -ForegroundColor Green
}

Write-Host ""
Write-Host "📦 Instalando dependencias..." -ForegroundColor Cyan
npm install

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Error instalando dependencias" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "🗄️  Generando Prisma Client..." -ForegroundColor Cyan
npx prisma generate

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Error generando Prisma Client" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "🔄 Sincronizando base de datos..." -ForegroundColor Cyan
npx prisma db push

if ($LASTEXITCODE -ne 0) {
    Write-Host "⚠️  Error en db push. Verifica que PostgreSQL esté corriendo." -ForegroundColor Yellow
    Write-Host "   Puedes intentar manualmente: npx prisma db push" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "✅ ¡Setup completado!" -ForegroundColor Green
Write-Host ""
Write-Host "📝 Próximos pasos:" -ForegroundColor Cyan
Write-Host "   1. Verifica .env.local (edita si necesitas)" -ForegroundColor White
Write-Host "   2. Ejecuta: npm run dev" -ForegroundColor White
Write-Host "   3. Abre: http://localhost:3000" -ForegroundColor White
Write-Host "   4. Sign up con email/password" -ForegroundColor White
Write-Host "   5. Aprueba tu usuario en DB:" -ForegroundColor White
Write-Host "      UPDATE users SET beta_access = true WHERE email = 'tu@email.com';" -ForegroundColor Yellow
Write-Host ""
Write-Host "🎉 ¡Listo para crear clips virales!" -ForegroundColor Cyan
