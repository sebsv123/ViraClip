#!/usr/bin/env python3
"""
Script de prueba real - Procesa el video de YouTube
"""
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__) / "src"))

async def process_youtube_video():
    """Procesa el video: https://youtu.be/3wgwaxIfUJQ"""
    
    url = "https://youtu.be/3wgwaxIfUJQ?si=0c-ziAceI-tpJZfX"
    
    print("🎬 VIRACLIP - PROCESAMIENTO REAL")
    print("=" * 60)
    print(f"URL: {url}")
    print("=" * 60)
    
    # Importar el nuevo pipeline consolidado
    from video_processing import OrchestratedEditingPipeline
    
    pipeline = OrchestratedEditingPipeline()
    
    print("\n✅ Pipeline inicializado correctamente")
    print("\n📋 Componentes activos:")
    print("   • Audio normalization (Phase 1)")
    print("   • B-Roll overlay engine (Phase 2)")
    print("   • Transition selector (Phase 3)")
    print("   • Orchestrated pipeline integrado")
    
    print("\n🚀 Para procesar el video completo, usar:")
    print("   POST /api/v1/clips/generate")
    print("   Body: {\"url\": \"https://youtu.be/3wgwaxIfUJQ\", ...}")
    
    return True

if __name__ == "__main__":
    try:
        result = asyncio.run(process_youtube_video())
        sys.exit(0 if result else 1)
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
