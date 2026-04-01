# Crear Acceso Directo en Escritorio (Windows)

## Método 1: PowerShell (Recomendado) ⭐

### Crear acceso directo automáticamente:

1. **Abre PowerShell como Administrador** (click derecho en menú inicio → Windows PowerShell → Ejecutar como administrador)

2. **Copia y pega este comando** (cambia la ruta si ViraClip está en otro lugar):

```powershell
$WshShell = New-Object -comObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("$env:USERPROFILE\Desktop\🚀 Deploy ViraClip.lnk")
$Shortcut.TargetPath = "powershell.exe"
$Shortcut.Arguments = "-ExecutionPolicy Bypass -NoProfile -File `"C:\Users\Sebitas\SupoClip-Propio\deploy.ps1`""
$Shortcut.WorkingDirectory = "C:\Users\Sebitas\SupoClip-Propio"
$Shortcut.Description = "Deploy ViraClip con un click"
$Shortcut.IconLocation = "C:\Windows\System32\shell32.dll,13"
$Shortcut.Save()
Write-Host "✓ Acceso directo creado en el escritorio!" -ForegroundColor Green
```

3. **Presiona Enter** → El acceso directo aparecerá en tu escritorio

4. **Para ejecutar:** Doble click en "🚀 Deploy ViraClip" en el escritorio

---

## Método 2: Manual (Si el automático falla)

### Crear acceso directo a mano:

1. **Click derecho en el escritorio** → Nuevo → Acceso directo

2. **En "Ubicación del elemento"** pega esto:
   ```
   powershell.exe -ExecutionPolicy Bypass -NoProfile -File "C:\Users\Sebitas\SupoClip-Propio\deploy.ps1"
   ```

3. **Nombre:** `🚀 Deploy ViraClip`

4. **Click derecho en el acceso directo** → Propiedades → Cambiar icono → Elegir uno que te guste

5. **En "Iniciar en"** poner:
   ```
   C:\Users\Sebitas\SupoClip-Propio
   ```

6. **Aplicar** → Aceptar

---

## Método 3: Batch File (Alternativo)

Si PowerShell da problemas, usa `deploy.bat`:

1. **Click derecho en el escritorio** → Nuevo → Acceso directo

2. **Ubicación:**
   ```
   C:\Users\Sebitas\SupoClip-Propio\deploy.bat
   ```

3. **Nombre:** `Deploy ViraClip`

4. **Aplicar**

---

## 🔒 Solución a "Los scripts están deshabilitados"

Si al ejecutar sale error de "execution policy", ejecuta esto **una sola vez** en PowerShell como Admin:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force
```

Esto permite ejecutar scripts locales sin problemas de seguridad.

---

## ✅ Verificar que Funciona

1. **Doble click** en el acceso directo del escritorio
2. Debería abrirse una ventana PowerShell colorida mostrando:
   - ✓ Containers detenidos
   - ✓ Build completado
   - ✓ Servicios iniciados
   - ✓ Migraciones aplicadas
   - URLs del frontend/backend
3. Al finalizar, presiona cualquier tecla para cerrar

---

## 🎨 Personalizar Icono (Opcional)

Windows tiene iconos built-in en:
- `C:\Windows\System32\shell32.dll` (muchos iconos)
- `C:\Windows\System32\imageres.dll` (más iconos modernos)

**Mejores iconos para deploy:**
- `shell32.dll` icono 13 (rocket) ← recomendado
- `shell32.dll` icono 44 (play button)
- `imageres.dll` icono 76 (gear)

**Para cambiar icono:**
1. Click derecho en acceso directo → Propiedades
2. Cambiar icono
3. Examinar → pegar ruta de DLL
4. Elegir icono → Aplicar

---

## 📝 Script Incluye

El script `deploy.ps1` ejecuta automáticamente:

✅ `docker-compose down` (limpia containers viejos)  
✅ `docker-compose build` (compila cambios nuevos)  
✅ `docker-compose up -d` (inicia servicios)  
✅ Espera 10s a que DB esté lista  
✅ Ejecuta migraciones SQL  
✅ Verifica health checks  
✅ Muestra logs recientes  
✅ Imprime URLs importantes  

**Total:** ~3-5 minutos dependiendo de tu PC.

---

## 🚀 Pro Tip

Crea **dos accesos directos** en el escritorio:

1. **"🚀 Deploy ViraClip"** → `deploy.ps1` (full rebuild)
2. **"⚡ Start ViraClip"** → `docker-compose up -d` (start rápido sin build)

El segundo es útil para inicios rápidos sin cambios en código.

**Para "Start rápido":**
```powershell
$Shortcut.TargetPath = "powershell.exe"
$Shortcut.Arguments = "-Command `"cd 'C:\Users\Sebitas\SupoClip-Propio'; docker-compose up -d; pause`""
```

---

## ❓ Troubleshooting

### "No se reconoce docker-compose"
- Instala Docker Desktop y reinicia PC
- Verifica que Docker Desktop esté corriendo (icono en system tray)

### "Acceso denegado"
- Ejecuta PowerShell como Administrador
- O cambia execution policy (ver arriba)

### "No encuentra deploy.ps1"
- Verifica la ruta en el acceso directo
- Debe ser la ruta **absoluta** completa

### Script se cierra inmediatamente
- Abre PowerShell manualmente
- Navega a carpeta del proyecto: `cd C:\Users\Sebitas\SupoClip-Propio`
- Ejecuta: `.\deploy.ps1`
- Lee los errores que aparezcan

---

¡Listo! Ahora tienes deploy con un solo click desde el escritorio 🚀
