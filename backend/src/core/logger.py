"""
Configuración de logging estructurado para ViraClip.

Proporciona logs con formato consistente:
timestamp | nivel | módulo | mensaje
"""

import logging
import sys


def setup_logger(name: str) -> logging.Logger:
    """
    Crea un logger con formato estructurado.
    
    Args:
        name: Nombre del módulo (ej: "video_service")
        
    Returns:
        Logger configurado
        
    Ejemplo:
        logger = setup_logger("video_service")
        logger.info("[TRANSCRIPTION] Completado: 847 palabras")
        logger.warning("[LLM] Phi-3 devolvió score 0 para segmento 3")
        logger.error("[FRANKENSTEIN] FFmpeg falló: código 1")
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    
    # Evitar duplicados si ya tiene handlers
    if logger.handlers:
        return logger
    
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    
    # Formato con timestamp, nivel y módulo — fácil de filtrar
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s',
        datefmt='%H:%M:%S'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    
    return logger


# Alias de compatibilidad
get_logger = setup_logger
