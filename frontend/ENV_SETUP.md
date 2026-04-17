# Frontend Environment Setup

## 📋 Crear archivo `.env.local`

Copia este contenido en `frontend/.env.local`:

```bash
# Database
DATABASE_URL="postgresql://viraclip:your_password@localhost:5432/viraclip?schema=public"

# Better Auth
BETTER_AUTH_SECRET="generate-random-32-char-secret" # Run: openssl rand -base64 32
BETTER_AUTH_URL="http://localhost:3000"

# Google OAuth (Get from https://console.cloud.google.com)
GOOGLE_CLIENT_ID="your-google-client-id.apps.googleusercontent.com"
GOOGLE_CLIENT_SECRET="your-google-client-secret"

# Backend API
NEXT_PUBLIC_API_URL="http://localhost:8000"

# Optional: Email (for password reset, notifications)
EMAIL_SERVER="smtp://user:pass@smtp.gmail.com:587"
EMAIL_FROM="noreply@viraclip.com"
```

## 🔑 Obtener Google OAuth Credentials

1. Ve a [Google Cloud Console](https://console.cloud.google.com)
2. Crea un nuevo proyecto "ViraClip"
3. Habilita "Google+ API"
4. Ve a "Credentials" → "Create Credentials" → "OAuth 2.0 Client ID"
5. Application type: "Web application"
6. Authorized redirect URIs:
   - `http://localhost:3000/api/auth/callback/google`
   - `https://viraclip.com/api/auth/callback/google` (producción)
7. Copia Client ID y Client Secret

## 🔐 Generar BETTER_AUTH_SECRET

```bash
openssl rand -base64 32
```

O en Node.js:
```bash
node -e "console.log(require('crypto').randomBytes(32).toString('base64'))"
```

## 🗄️ Database URL

Si usas el PostgreSQL del backend (docker-compose):
```
DATABASE_URL="postgresql://viraclip:viraclip_password@localhost:5432/viraclip?schema=public"
```

## ✅ Verificar variables

```bash
cd frontend
node -e "require('dotenv').config({ path: '.env.local' }); console.log(process.env.DATABASE_URL ? '✅ DB configured' : '❌ Missing DB')"
```
