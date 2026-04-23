#!/usr/bin/env python3
"""
Test E2E completo: Descarga YouTube -> Procesa con ViraClip -> Muestra resultados
"""
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# Configuración
YOUTUBE_URL = "https://youtu.be/DvfjmBa3Kvk"
WORKDIR = "/tmp/viraclip_e2e_test"
DOCKER_COMPOSE_FILE = "/home/_sebastian/CascadeProjects/ViraClip/docker-compose.yml"


def run_command(cmd, cwd=None, timeout=300):
    """Ejecutar comando y retornar output."""
    print(f"   🏃 {cmd[:80]}...")
    result = subprocess.run(
        cmd,
        shell=True,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout
    )
    if result.returncode != 0:
        print(f"   ⚠️  stderr: {result.stderr[:200]}")
    return result


def download_youtube(url, output_dir):
    """Descargar video de YouTube."""
    print("\n📥 Paso 1: Descargando video de YouTube...")
    
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Verificar yt-dlp
    result = run_command("which yt-dlp || pip3 install yt-dlp --break-system-packages 2>/dev/null || pip3 install yt-dlp --user")
    
    cmd = (
        f"yt-dlp -f 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best' "
        f"-o '{output_dir}/%(id)s.%(ext)s' "
        f"--merge-output-format mp4 "
        f"--no-playlist "
        f"'{url}'"
    )
    
    result = run_command(cmd, timeout=300)
    
    if result.returncode != 0:
        print(f"   ❌ Error descargando: {result.stderr}")
        return None
    
    # Encontrar archivo descargado
    files = list(output_dir.glob("*.mp4"))
    if not files:
        print("   ❌ No se encontró archivo descargado")
        return None
    
    video_file = files[0]
    size = video_file.stat().st_size / (1024 * 1024)  # MB
    print(f"   ✅ Descargado: {video_file.name} ({size:.1f} MB)")
    
    return video_file


def copy_to_container(video_file):
    """Copiar video al contenedor de ViraClip."""
    print("\n📦 Paso 2: Copiando video al contenedor...")
    
    # Verificar contenedor
    result = run_command("docker ps | grep viraclip-backend || docker-compose -f {} ps | grep backend".format(DOCKER_COMPOSE_FILE))
    if "backend" not in result.stdout:
        print("   🚀 Iniciando contenedores...")
        run_command(f"docker-compose -f {DOCKER_COMPOSE_FILE} up -d", cwd="/home/_sebastian/CascadeProjects/ViraClip")
        time.sleep(10)
    
    # Copiar archivo
    container_name = "viraclip-backend-1"
    result = run_command(f"docker cp '{video_file}' {container_name}:/app/uploads/")
    
    if result.returncode != 0:
        print(f"   ❌ Error copiando: {result.stderr}")
        return None
    
    print(f"   ✅ Copiado a contenedor: /app/uploads/{video_file.name}")
    return video_file.name


def create_task(video_filename):
    """Crear tarea de procesamiento en ViraClip."""
    print("\n🎯 Paso 3: Creando tarea de procesamiento...")
    
    payload = {
        "source_type": "upload",
        "video_filename": video_filename,
        "platform": "tiktok",
        "options": {
            "max_clips": 3,
            "min_duration": 15,
            "max_duration": 60,
            "background_composite_enabled": True,
            "sam2_enabled": True,
            "generate_captions": True,
            "virality_threshold": 7.0
        }
    }
    
    # Crear archivo temporal con el payload
    payload_file = f"{WORKDIR}/task_payload.json"
    with open(payload_file, 'w') as f:
        json.dump(payload, f)
    
    # Enviar a la API
    cmd = (
        f"curl -s -X POST http://localhost:8000/api/tasks "
        f"-H 'Content-Type: application/json' "
        f"-d @{payload_file}"
    )
    
    result = run_command(cmd, timeout=30)
    
    if result.returncode != 0:
        print(f"   ❌ Error creando tarea: {result.stderr}")
        return None
    
    try:
        response = json.loads(result.stdout)
        task_id = response.get("task_id") or response.get("id")
        print(f"   ✅ Tarea creada: {task_id}")
        return task_id
    except json.JSONDecodeError:
        print(f"   ⚠️  Respuesta no es JSON: {result.stdout[:200]}")
        return None


def monitor_task(task_id, timeout=600):
    """Monitorear progreso de la tarea."""
    print(f"\n⏳ Paso 4: Monitoreando tarea {task_id}...")
    print(f"   Timeout: {timeout//60} minutos")
    
    start_time = time.time()
    last_status = None
    
    while time.time() - start_time < timeout:
        # Consultar estado
        result = run_command(f"curl -s http://localhost:8000/api/tasks/{task_id}", timeout=10)
        
        if result.returncode == 0:
            try:
                status = json.loads(result.stdout)
                current = status.get("status", "unknown")
                
                if current != last_status:
                    print(f"   📊 Estado: {current}")
                    last_status = current
                
                if current in ["completed", "done", "finished"]:
                    print(f"   ✅ Tarea completada!")
                    return status
                elif current in ["failed", "error"]:
                    print(f"   ❌ Tarea falló: {status}")
                    return None
                    
            except json.JSONDecodeError:
                pass
        
        # Mostrar progreso cada 30 segundos
        elapsed = int(time.time() - start_time)
        if elapsed % 30 == 0:
            print(f"   ⏱️  {elapsed//60}m {elapsed%60}s elapsed...")
        
        time.sleep(5)
    
    print(f"   ⏰ Timeout alcanzado")
    return None


def show_results(task_status):
    """Mostrar resultados del procesamiento."""
    print("\n🎬 Paso 5: Resultados del procesamiento")
    print("=" * 60)
    
    if not task_status:
        print("❌ No hay resultados disponibles")
        return
    
    clips = task_status.get("clips", []) or task_status.get("results", [])
    
    print(f"\n📊 Resumen:")
    print(f"   • Clips generados: {len(clips)}")
    print(f"   • Estado: {task_status.get('status', 'unknown')}")
    
    if clips:
        print(f"\n🎞️  Clips generados:")
        for i, clip in enumerate(clips, 1):
            print(f"\n   Clip {i}:")
            print(f"      • ID: {clip.get('id', 'N/A')}")
            print(f"      • Score viral: {clip.get('viral_score', 'N/A')}")
            print(f"      • Duración: {clip.get('duration', 'N/A')}s")
            print(f"      • Modo: {clip.get('composite_mode', 'N/A')}")
            print(f"      • Path: {clip.get('output_path', 'N/A')}")
    
    print("\n" + "=" * 60)


async def main():
    """Flujo E2E completo."""
    print("=" * 60)
    print("🚀 ViraClip E2E Test - YouTube Processing")
    print("=" * 60)
    print(f"\n📹 URL: {YOUTUBE_URL}")
    print(f"📁 Workdir: {WORKDIR}")
    
    # Limpiar directorio anterior si existe
    if os.path.exists(WORKDIR):
        import shutil
        shutil.rmtree(WORKDIR)
    
    try:
        # Paso 1: Descargar
        video_file = download_youtube(YOUTUBE_URL, f"{WORKDIR}/downloads")
        if not video_file:
            print("\n❌ Fallo en descarga")
            return 1
        
        # Paso 2: Copiar a contenedor
        video_filename = copy_to_container(video_file)
        if not video_filename:
            print("\n❌ Fallo en copia")
            return 1
        
        # Paso 3: Crear tarea
        task_id = create_task(video_filename)
        if not task_id:
            print("\n❌ Fallo creando tarea")
            return 1
        
        # Paso 4: Monitorear
        task_status = monitor_task(task_id)
        
        # Paso 5: Mostrar resultados
        show_results(task_status)
        
        # Guardar reporte
        report_file = f"{WORKDIR}/report.json"
        with open(report_file, 'w') as f:
            json.dump({
                "youtube_url": YOUTUBE_URL,
                "video_file": str(video_file),
                "task_id": task_id,
                "status": task_status
            }, f, indent=2)
        
        print(f"\n📄 Reporte guardado: {report_file}")
        
        if task_status and task_status.get("status") in ["completed", "done", "finished"]:
            print("\n✨ Proceso E2E completado exitosamente!")
            return 0
        else:
            print("\n⚠️  Proceso incompleto")
            return 1
            
    except KeyboardInterrupt:
        print("\n\n🛑 Interrumpido por usuario")
        return 130
    except Exception as e:
        print(f"\n❌ Error inesperado: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(asyncio.run(main()))
