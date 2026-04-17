# 🚀 ViraClip Frontend - Quickstart MVP

## ✅ Lo que acabamos de implementar

### **Fase 1: Setup Base** ✅
- ✅ Schema Prisma actualizado (User con waitlist, Clip model)
- ✅ Better-auth configurado con Google OAuth
- ✅ API Client para conectar con backend Python
- ✅ Middleware de protección de rutas

### **Fase 2: Componentes Dashboard** ✅
- ✅ Dashboard Layout con Sidebar + Header
- ✅ Dashboard principal (ya existía, mejorado)
- ✅ Página de Waitlist Pending
- ✅ Componentes reutilizables

## 📦 Instalación (3 comandos)

### 1. Instalar dependencias
```bash
cd frontend
npm install
```

### 2. Configurar environment
Crea `frontend/.env.local` con:

```bash
# Database (usa el mismo PostgreSQL del backend)
DATABASE_URL="postgresql://viraclip:viraclip_password@localhost:5432/viraclip?schema=public"

# Better Auth
BETTER_AUTH_SECRET="$(openssl rand -base64 32)"
BETTER_AUTH_URL="http://localhost:3000"

# Google OAuth (obtener de Google Cloud Console)
GOOGLE_CLIENT_ID="your-google-client-id.apps.googleusercontent.com"
GOOGLE_CLIENT_SECRET="your-google-client-secret"

# Backend API
NEXT_PUBLIC_API_URL="http://localhost:8000"
```

### 3. Ejecutar migraciones y generar Prisma
```bash
npx prisma generate
npx prisma db push
```

### 4. Iniciar desarrollo
```bash
npm run dev
```

Abre [http://localhost:3000](http://localhost:3000)

---

## 🔑 Obtener Google OAuth Credentials

1. Ve a [Google Cloud Console](https://console.cloud.google.com)
2. Crea proyecto "ViraClip"
3. Habilita "Google+ API"
4. Credentials → Create OAuth 2.0 Client ID
5. Application type: **Web application**
6. Authorized redirect URIs:
   ```
   http://localhost:3000/api/auth/callback/google
   ```
7. Copia Client ID y Client Secret al `.env.local`

---

## 🗄️ Database Schema Changes

Se añadieron campos a `User`:
- `waitlist_status` (pending|approved|rejected)
- `beta_access` (boolean)
- `clips_this_month` (int)
- `last_reset_date` (timestamp)

Nuevo modelo `Clip`:
- `id`, `task_id`, `user_id`
- `filename`, `duration`, `file_size`
- `viral_score`, `rating`, `thumbs`
- `feedback_text`

---

## 📁 Estructura Creada

```
frontend/
├── src/
│   ├── app/
│   │   ├── dashboard/
│   │   │   ├── layout.tsx ✅ (protege con auth)
│   │   │   └── page.tsx ✅ (ya existía)
│   │   └── waitlist-pending/
│   │       └── page.tsx ✅ (nuevo)
│   ├── components/
│   │   └── dashboard/
│   │       ├── sidebar.tsx ✅ (nuevo)
│   │       └── header.tsx ✅ (nuevo)
│   └── lib/
│       ├── auth.ts ✅ (actualizado con Google OAuth)
│       └── api-client.ts ✅ (nuevo, conecta con FastAPI)
├── prisma/
│   └── schema.prisma ✅ (actualizado)
├── middleware.ts ✅ (actualizado)
├── ENV_SETUP.md ✅ (guía de variables)
└── .env.local (crear manualmente)
```

---

## 🎯 Flujo de Usuario

### 1. Landing Page (`/`)
- Hero con features
- CTA "Start Free" → Sign Up

### 2. Sign Up
- Google OAuth (1-click)
- Email/Password (fallback)
- Auto-creado con `waitlist_status=pending`

### 3. Waitlist Pending (`/waitlist-pending`)
- Mensaje de espera
- Info de posición en cola
- Opción de compartir para saltar fila

### 4. Aprobación Manual (Admin)
```sql
-- Aprobar usuario manualmente en DB
UPDATE users 
SET beta_access = true, waitlist_status = 'approved' 
WHERE email = 'usuario@ejemplo.com';
```

### 5. Dashboard (`/dashboard`)
- Solo accesible con `beta_access = true`
- Crear clips con formulario completo
- Ver historial de tareas
- Stats de uso

---

## 🔌 Conexión con Backend

El API Client (`lib/api-client.ts`) conecta con estos endpoints:

```typescript
// Crear tarea
await api.createTask({
  source: "https://youtube.com/watch?v=...",
  caption_template: "pop_in",
  include_broll: true
}, userId);

// Stream progress (SSE)
const eventSource = api.streamTaskProgress(taskId, userId, (event) => {
  console.log(event.progress, event.status);
});

// Rate clip
await api.thumbsClip(clipId, 'thumbs_up', userId);

// Download
const blob = await api.downloadClip(clipId, userId, 'tiktok');
```

---

## 🧪 Testing

### 1. Sign Up Flow
```bash
# Inicia el frontend
npm run dev

# Navega a http://localhost:3000
# Click "Start Free" → Sign Up
# Usa Google OAuth o Email
```

### 2. Verificar Waitlist
```bash
# Deberías ver /waitlist-pending
# Verifica en DB:
psql -U viraclip -d viraclip -c "SELECT email, waitlist_status, beta_access FROM users;"
```

### 3. Aprobar Usuario
```sql
UPDATE users 
SET beta_access = true 
WHERE email = 'tu-email@gmail.com';
```

### 4. Acceder Dashboard
```bash
# Refresca el navegador
# Deberías ser redirigido a /dashboard
```

---

## 🎨 Customización

### Cambiar colores del tema
Edita `globals.css`:
```css
:root {
  --primary-cyan: hsl(180, 100%, 50%);
  --primary-purple: hsl(270, 100%, 65%);
  --primary-pink: hsl(330, 100%, 60%);
}
```

### Ajustar límites de clips
Edita `components/dashboard/sidebar.tsx`:
```typescript
const clipsLimit = 10; // Cambiar a 20, 50, etc.
```

---

## 🐛 Troubleshooting

### Error: `Cannot connect to database`
```bash
# Verifica que PostgreSQL esté corriendo
docker ps | grep postgres

# Verifica DATABASE_URL en .env.local
echo $DATABASE_URL
```

### Error: `Google OAuth redirect mismatch`
1. Ve a Google Cloud Console
2. Credentials → tu OAuth client
3. Añade exactamente: `http://localhost:3000/api/auth/callback/google`

### Error: TypeScript errors en IDE
```bash
# Regenera Prisma client
npx prisma generate

# Reinicia TypeScript server en VSCode
Ctrl+Shift+P → "TypeScript: Restart TS Server"
```

---

## ✨ Próximos Pasos

1. **Deploy a Producción**
   - Configurar Vercel/Netlify
   - Añadir dominio custom
   - Configurar Google OAuth producción

2. **Features Pendientes**
   - Página de clips individuales (`/dashboard/clips/[id]`)
   - Página de settings
   - Sistema de notificaciones
   - Admin dashboard para aprobar waitlist

3. **Optimizaciones**
   - Server Actions para forms
   - React Query para cache
   - Optimistic UI updates
   - Image optimization

---

## 📞 Soporte

- Docs: `frontend/ENV_SETUP.md`
- Plan completo: `~/.windsurf/plans/viraclip-production-mvp-e4c206.md`

**¡Listo para probar! 🚀**
