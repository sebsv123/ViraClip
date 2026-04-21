---
# Permisos del Agente — ViraClip

## REQUIEREN CONFIRMACIÓN EXPLÍCITA (preguntar siempre antes)
- Modificar docker-compose.yml
- Modificar backend/src/services/coordinator.py
- Modificar cualquier fichero de migraciones de base de datos
- Ejecutar docker compose down en producción
- Modificar .env o .env.example
- Cambiar puertos expuestos

## PERMITIDO SIN CONFIRMACIÓN
- Leer cualquier fichero del repo
- Crear ficheros nuevos en directorios existentes
- Modificar ficheros dentro de backend/src/services/ 
  (excepto coordinator.py)
- Ejecutar docker exec para inspección (no modificación)
- Añadir tests

## NUNCA HACER
- Borrar volúmenes Docker con docker volume rm
- Hacer force push a main o version-basica
- Exponer credenciales en logs o ficheros
---
