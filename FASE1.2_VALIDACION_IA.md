# FASE 1.2: Validación IA - Dashboard de Métricas y Anomalías

## 🎯 Objetivo
Implementar un sistema completo de validación y monitoreo de la calidad del análisis de IA para asegurar que el LLM mejorado (FASE 1.1) funciona correctamente en producción.

---

## ✅ Implementado

### **1. Dashboard de Métricas de IA** ⭐⭐⭐⭐⭐

#### Endpoint: `GET /admin/ai-metrics`

**Métricas incluidas:**

**A. Task Success Summary:**
- Total de tareas procesadas
- Tareas completadas vs fallidas
- **Tareas sin clips** (AI no encontró segmentos)
- Success rate general
- Rate de tareas con clips generados

**B. Distribución de Scores de Viralidad:**
- Distribución por score (1-10)
- Estadísticas: mean, median, stdev, min, max
- Percentiles: P25, P50 (median), P75, P90
- Total de clips analizados

**C. Detección de Anomalías:**

| Anomalía | Threshold | Severidad | Descripción |
|----------|-----------|-----------|-------------|
| **High No-Clips Rate** | >10% | High si >25% | Muchas tareas sin clips generados |
| **Uniform Scores** | ≤2 scores únicos | High | AI retorna siempre los mismos valores |
| **Low Variance** | σ <1.0 | Medium | Scores demasiado similares entre sí |
| **High Failure Rate** | >20% | High si >40% | Muchas tareas fallando |

**D. Recomendaciones Automáticas:**
- Basadas en anomalías detectadas
- Acciones específicas para cada issue
- Priorización por severidad

**Ejemplo de Response:**
```json
{
  "period": "last_7_days",
  "summary": {
    "total_tasks": 150,
    "completed_tasks": 135,
    "failed_tasks": 15,
    "tasks_without_clips": 8,
    "success_rate": 90.0,
    "tasks_with_clips_rate": 94.07
  },
  "virality_distribution": {
    "by_score": {"8": 45, "7": 38, "9": 22, "6": 15},
    "statistics": {
      "mean": 7.65,
      "median": 8.0,
      "stdev": 1.12,
      "min": 5,
      "max": 10,
      "total_clips": 120
    },
    "percentiles": {
      "p25": 7.0,
      "p50": 8.0,
      "p75": 8.5,
      "p90": 9.0
    }
  },
  "anomalies": [
    {
      "type": "high_no_clips_rate",
      "severity": "medium",
      "value": 5.93,
      "description": "8 tasks completed but no clips generated (5.9%)",
      "recommendation": "Check LLM service health and prompt quality."
    }
  ],
  "recommendations": [
    {
      "type": "all_good",
      "message": "No anomalies detected. AI analysis is performing well! 🎉"
    }
  ]
}
```

---

### **2. Tasks Without Clips Analysis** ⭐⭐⭐⭐

#### Endpoint: `GET /admin/ai-metrics/tasks-without-clips`

Retorna lista detallada de tareas completadas pero sin clips generados.

**Para cada tarea incluye:**
- Task ID
- Fecha de creación
- Estado actual
- Mensaje de error (si existe)
- Mensaje de progreso
- Título del video
- URL del video

**Uso:**
```bash
curl http://localhost:8000/admin/ai-metrics/tasks-without-clips?limit=20
```

**Causas comunes identificadas:**
1. Video demasiado corto (<30s)
2. No speech detected (solo música)
3. Transcripción de baja calidad
4. Contenido no apto para clips virales
5. LLM timeout o error
6. Prompt no trigger correctamente

---

### **3. Score Outliers Detection** ⭐⭐⭐⭐

#### Endpoint: `GET /admin/ai-metrics/score-outliers`

Detecta clips con scores anómalos (outliers estadísticos).

**Método:**
- Calcula mean y standard deviation de scores
- Identifica outliers: `|score - mean| > 2σ`
- Clasifica como "high" o "low"

**Response:**
```json
{
  "statistics": {
    "mean": 7.5,
    "stdev": 1.2,
    "threshold_high": 9.9,
    "threshold_low": 5.1
  },
  "outliers": [
    {
      "clip_id": "abc123",
      "filename": "clip_001.mp4",
      "virality_score": 10,
      "duration": 45,
      "hook_title": "Amazing discovery!",
      "task_id": "task_xyz",
      "video_title": "My Journey",
      "deviation_from_mean": 2.5,
      "type": "high"
    }
  ],
  "count": 5
}
```

**Utilidad:**
- Identificar false positives (scores muy altos sospechosos)
- Detectar clips con scores inusualmente bajos
- Validar consistencia del scoring

---

### **4. LLM Validation Endpoint** ⭐⭐⭐⭐⭐

#### Endpoint: `POST /admin/ai-metrics/validate-llm`

Ejecuta tests automáticos con transcript conocido para validar que el LLM funciona correctamente.

**Tests incluidos:**

1. **AI Analysis Execution**
   - Verifica que LLM retorna segmentos
   - Pass si encuentra al menos 1 segmento

2. **Score Range Validation**
   - Verifica que scores están en rango 1-10
   - Pass si todos los scores son válidos

3. **Score Variance**
   - Verifica que hay variación en scores
   - Warning si varianza <0.5 (scores muy uniformes)

4. **Segment Duration**
   - Verifica duración promedio de clips
   - Pass si 10-60s (ideal), Warning si fuera de rango

**Transcript de prueba:**
```
[00:00 - 00:15] I'm about to reveal a secret that billion-dollar companies don't want you to know.
[00:15 - 00:30] This simple trick changed my life completely...
```

**Response:**
```json
{
  "timestamp": "2026-03-30T16:30:00Z",
  "overall_status": "healthy",
  "tests": [
    {
      "name": "AI Analysis Execution",
      "status": "pass",
      "details": "Found 3 segments"
    },
    {
      "name": "Score Range Validation",
      "status": "pass",
      "details": "Scores: [8, 7, 9], All in range 1-10: True"
    },
    {
      "name": "Score Variance",
      "status": "pass",
      "details": "Variance: 0.89 (should be >0.5)"
    },
    {
      "name": "Segment Duration",
      "status": "pass",
      "details": "Avg duration: 32.5s (ideal: 10-60s)"
    }
  ],
  "summary": {
    "total_tests": 4,
    "passed": 4,
    "warnings": 0,
    "failed": 0
  }
}
```

---

### **5. Tests con Transcripts Reales** ⭐⭐⭐⭐

#### Archivo: `backend/tests/test_ai_validation.py` (18 tests)

**Tests implementados:**

1. **test_high_viral_potential_transcript**
   - Transcript con alto potencial viral
   - Espera scores promedio ≥6.0

2. **test_medium_viral_potential_transcript**
   - Contenido educativo moderado
   - Espera scores en rango 4.0-7.0

3. **test_low_viral_potential_transcript**
   - Contenido de bajo engagement
   - Espera scores ≤6.0

4. **test_score_variance**
   - Verifica que AI no retorna scores idénticos

5. **test_segment_duration_reasonable**
   - Valida duraciones 5-120s

6. **test_segments_dont_overlap**
   - Asegura que clips no se superponen

7. **test_hook_titles_generated**
   - Verifica que títulos existen y son razonables

8. **test_anomaly_detection_***
   - Tests para cada tipo de anomalía

9. **test_empty_transcript_handling**
   - Manejo de transcripts vacíos

10. **test_very_long_transcript**
    - Videos de 1+ hora (sin timeout)

**Ejecutar tests:**
```bash
cd backend
.venv/bin/pytest tests/test_ai_validation.py -v
```

---

### **6. Sample Transcripts Dataset** ⭐⭐⭐

#### Archivo: `backend/tests/fixtures/sample_transcripts.json`

**8 transcripts de prueba con rangos esperados:**

| Transcript | Tipo | Expected Score Range |
|------------|------|----------------------|
| **tech_tutorial_high_viral** | Tutorial viral | 7-10 |
| **storytelling_high_viral** | Historia personal | 8-10 |
| **educational_medium_viral** | Tutorial educativo | 5-7 |
| **vlog_medium_viral** | Vlog rutina | 4-6 |
| **podcast_low_viral** | Chat casual | 2-5 |
| **technical_lecture_low_viral** | Clase técnica | 3-5 |
| **no_speech_detected** | Solo música | 1-3 |
| **multilingual_unclear** | Lenguaje mixto | 2-5 |

**Uso en tests:**
```python
import json

with open('tests/fixtures/sample_transcripts.json') as f:
    samples = json.load(f)

transcript = samples["transcripts"]["tech_tutorial_high_viral"]["content"]
expected_range = samples["transcripts"]["tech_tutorial_high_viral"]["expected_score_range"]
```

---

## 📦 Archivos Creados

**Nuevos módulos:**
- `backend/src/api/routes/ai_metrics.py` (430 líneas) - Dashboard completo
- `backend/tests/test_ai_validation.py` (350 líneas) - 18 tests
- `backend/tests/fixtures/sample_transcripts.json` - Dataset de prueba

**Modificados:**
- `backend/src/api/routes/admin.py` - Incluye ai_metrics router
- `backend/src/main.py` - Registra ai_metrics y health routers

**Documentación:**
- `FASE1.2_VALIDACION_IA.md` - Este documento

---

## 🚀 Uso

### **1. Acceder al Dashboard**

```bash
# Métricas generales (últimos 7 días)
curl http://localhost:8000/admin/ai-metrics

# Métricas de 30 días
curl http://localhost:8000/admin/ai-metrics?days=30

# Tareas sin clips
curl http://localhost:8000/admin/ai-metrics/tasks-without-clips?limit=20

# Score outliers
curl http://localhost:8000/admin/ai-metrics/score-outliers?days=7

# Validar LLM
curl -X POST http://localhost:8000/admin/ai-metrics/validate-llm
```

**Nota:** Todos los endpoints requieren autenticación admin.

---

### **2. Interpretar Métricas**

**✅ Señales de Salud:**
- Success rate >90%
- Tasks with clips rate >85%
- Score variance >0.5
- Mean score 6-8 (contenido viral)
- No anomalías de alta severidad

**⚠️ Señales de Alerta:**
- Tasks without clips >10%
- Score variance <0.5 (uniformidad)
- High failure rate >20%
- Scores todos idénticos
- Mean score <4 (contenido muy pobre)

**🚨 Acción Inmediata Requerida:**
- Tasks without clips >25%
- Failure rate >40%
- LLM validation fails
- Scores uniformes (≤2 valores únicos)

---

### **3. Ejecutar Tests**

```bash
cd backend

# Tests de validación IA
.venv/bin/pytest tests/test_ai_validation.py -v

# Test específico
.venv/bin/pytest tests/test_ai_validation.py::test_high_viral_potential_transcript -v

# Con coverage
.venv/bin/pytest tests/test_ai_validation.py --cov=src.ai --cov=src.services.llm_service_improved
```

---

### **4. Monitoreo Proactivo**

**Setup de alertas (recomendado):**

```bash
# Cron job diario para validar LLM
0 9 * * * curl -X POST http://localhost:8000/admin/ai-metrics/validate-llm | \
  jq '.overall_status' | \
  grep -q "healthy" || echo "LLM validation failed!" | mail -s "ViraClip Alert" admin@example.com

# Check cada hora para anomalías
0 * * * * curl http://localhost:8000/admin/ai-metrics | \
  jq '.anomalies | length' | \
  awk '$1 > 0 {print "Anomalies detected!"; exit 1}'
```

---

## 📊 Impacto Esperado

| Métrica | Antes (FASE 1.1) | Después (FASE 1.2) | Mejora |
|---------|------------------|-------------------|--------|
| **AI debugging time** | 30-60 min | **5-10 min** | 5x |
| **False positive detection** | Manual | **Automático** | ∞ |
| **Issue detection** | Reactivo | **Proactivo** | 100% |
| **LLM health visibility** | None | **Real-time** | ✅ |
| **Anomaly awareness** | Ad-hoc | **Sistemático** | ✅ |

---

## 🐛 Troubleshooting

### Endpoint retorna 401 Unauthorized
```bash
# Verificar que tienes auth admin configurado
# Ver backend/src/admin_auth.py para detalles
```

### Métricas muestran 0 tasks
```bash
# Verificar que hay tareas procesadas
curl http://localhost:8000/admin/metrics | jq '.tasks.total_tasks'

# Si es 0, procesar algunos videos primero
```

### LLM validation fails
```bash
# 1. Verificar LLM service
curl http://localhost:8000/health/detailed | jq '.checks'

# 2. Ver logs
docker-compose logs backend | grep "LLM"

# 3. Verificar API keys
docker-compose exec backend env | grep "API_KEY"
```

### Scores todos uniformes (anomalía)
```bash
# Posibles causas:
# 1. LLM retornando default values
# 2. Prompt no está generando variación
# 3. Validación Pydantic muy estricta

# Solución:
# - Revisar src/services/llm_service_improved.py
# - Ajustar prompt para más variación
# - Verificar que text-based fallback no se usa siempre
```

### Tasks without clips muy alto (>25%)
```bash
# Investigar causas:
curl http://localhost:8000/admin/ai-metrics/tasks-without-clips?limit=50

# Patrones comunes:
# - Videos muy cortos
# - Sin speech (solo música)
# - Idioma no soportado
# - Contenido técnico/aburrido
# - Prompt demasiado restrictivo
```

---

## 🔜 Mejoras Futuras (Opcionales)

### **Frontend Dashboard**
- Gráficos interactivos con Chart.js
- Visualización de score distribution
- Timeline de anomalías
- Drill-down en tasks sin clips

### **Advanced Analytics**
- Correlación video_title → score promedio
- Análisis por nicho/categoría
- Predicción de éxito antes de procesar
- A/B testing de prompts

### **Automated Actions**
- Auto-retry tasks sin clips con prompt mejorado
- Email/Slack alerts en anomalías críticas
- Auto-tune prompt basado en métricas
- Self-healing LLM service

---

## ✅ Checklist de Validación

Antes de considerar FASE 1.2 completa:

- [x] Endpoint `/admin/ai-metrics` funcional
- [x] Detección de 4+ tipos de anomalías
- [x] Tests con 8+ sample transcripts
- [x] LLM validation endpoint operativo
- [x] 18+ tests unitarios passing
- [x] Documentación completa
- [ ] Deploy y verificación en producción
- [ ] Setup de alertas (opcional)
- [ ] Frontend dashboard (opcional)

---

## 📝 Resumen

**FASE 1.2 completa** con:

1. ✅ **Dashboard de métricas** (`/admin/ai-metrics`)
   - Task success rate
   - Score distribution con estadísticas
   - Detección automática de 4 anomalías
   - Recomendaciones basadas en datos

2. ✅ **Análisis profundo**
   - Tasks without clips (debugging)
   - Score outliers (false positives)
   - LLM validation (health check)

3. ✅ **Tests comprehensivos**
   - 18 tests unitarios
   - 8 sample transcripts
   - Validación de rango, varianza, duración

4. ✅ **Documentación completa**
   - Guía de uso
   - Interpretación de métricas
   - Troubleshooting

**Sistema ahora tiene:**
- 🔍 Visibilidad completa de calidad de IA
- 🚨 Detección proactiva de issues
- 📊 Métricas accionables
- 🧪 Validación automatizada

**Próximo paso:** Deploy y monitoreo en producción 🚀

---

**Fecha:** Marzo 30, 2026  
**Versión:** 1.2.0 (FASE 1.2 completa)  
**Status:** ✅ AI validation ready
