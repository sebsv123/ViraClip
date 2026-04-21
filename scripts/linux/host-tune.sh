#!/usr/bin/env bash
# host-tune.sh — ViraClip Host Performance Tuning
# Target: Linux systems with NVIDIA GPUs for AI/ML video processing
# Run: sudo bash host-tune.sh
# Safe to re-run: yes (idempotent)

set -euo pipefail

LOG_FILE="/var/log/viraclip/host-tune.log"
VIRACLIP_USER="${VIRACLIP_USER:-$(logname 2>/dev/null || echo "$USER")}"

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")"

log() {
    local msg="$(date '+%Y-%m-%dT%H:%M:%S') $1"
    echo "$msg"
    echo "$msg" >> "$LOG_FILE"
}

log "=== ViraClip Host Tuning START ==="

# ── BLOQUE 1: SYSCTL KERNEL PARAMETERS ─────────────────────────────────────────
log "SYSCTL: Configurando parámetros del kernel..."

# vm.swappiness: Reducir uso de swap (priorizar RAM)
if [[ "$(cat /proc/sys/vm/swappiness)" != "10" ]]; then
    sysctl -w vm.swappiness=10 2>/dev/null || true
    echo 'vm.swappiness=10' > /etc/sysctl.d/99-viraclip-vm.conf
    log "  vm.swappiness: → 10"
else
    log "  vm.swappiness: ya en 10, skip"
fi

# net.core.somaxconn: Aumentar backlog de conexiones para FastAPI/Redis
if [[ "$(cat /proc/sys/net/core/somaxconn)" != "65535" ]]; then
    sysctl -w net.core.somaxconn=65535 2>/dev/null || true
    echo 'net.core.somaxconn=65535' > /etc/sysctl.d/99-viraclip-net.conf
    log "  net.core.somaxconn: → 65535"
else
    log "  net.core.somaxconn: ya en 65535, skip"
fi

# fs.file-max: Aumentar límite de file descriptors (FFmpeg + asyncio)
if [[ "$(cat /proc/sys/fs/file-max)" != "2097152" ]]; then
    sysctl -w fs.file-max=2097152 2>/dev/null || true
    echo 'fs.file-max=2097152' >> /etc/sysctl.d/99-viraclip-fs.conf
    log "  fs.file-max: → 2097152"
else
    log "  fs.file-max: ya en 2097152, skip"
fi

# net.ipv4.tcp_fastopen: Activar TFO para conexiones más rápidas
if [[ "$(cat /proc/sys/net/ipv4/tcp_fastopen 2>/dev/null || echo "0")" != "3" ]]; then
    sysctl -w net.ipv4.tcp_fastopen=3 2>/dev/null || true
    echo 'net.ipv4.tcp_fastopen=3' >> /etc/sysctl.d/99-viraclip-net.conf
    log "  net.ipv4.tcp_fastopen: → 3 (client+server)"
else
    log "  net.ipv4.tcp_fastopen: ya en 3, skip"
fi

# vm.dirty_ratio: Permitir más escrituras en buffer antes de flush
if [[ "$(cat /proc/sys/vm/dirty_ratio)" != "40" ]]; then
    sysctl -w vm.dirty_ratio=40 2>/dev/null || true
    sysctl -w vm.dirty_background_ratio=10 2>/dev/null || true
    echo 'vm.dirty_ratio=40' > /etc/sysctl.d/99-viraclip-vm.conf
    echo 'vm.dirty_background_ratio=10' >> /etc/sysctl.d/99-viraclip-vm.conf
    log "  vm.dirty_ratio: → 40, vm.dirty_background_ratio: → 10"
else
    log "  vm.dirty_ratio: ya en 40, skip"
fi

# Aplicar cambios de sysctl
sysctl --system 2>/dev/null || log "  sysctl --system ejecutado"

# ── BLOQUE 2: TRANSPARENT HUGEPAGES ─────────────────────────────────────────
log "THP: Configurando Transparent HugePages..."

THP_PATH="/sys/kernel/mm/transparent_hugepage/enabled"
if [[ -f "$THP_PATH" ]]; then
    CURRENT_THP=$(cat "$THP_PATH" 2>/dev/null | grep -oP '\[\K[^\]]+' || echo "unknown")
    if [[ "$CURRENT_THP" != "never" ]]; then
        echo never > "$THP_PATH" 2>/dev/null || log "  WARN: No se pudo deshabilitar THP (requiere root)"
        if [[ -f /etc/default/grub ]]; then
            if ! grep -q "transparent_hugepage=never" /etc/default/grub 2>/dev/null; then
                sed -i 's/GRUB_CMDLINE_LINUX="/GRUB_CMDLINE_LINUX="transparent_hugepage=never /' /etc/default/grub 2>/dev/null || true
                log "  THP: Añadido a GRUB_CMDLINE_LINUX (requiere update-grub y reboot)"
            fi
        fi
        log "  THP: $CURRENT_THP → never"
    else
        log "  THP: ya en never, skip"
    fi
else
    log "  THP: $THP_PATH no existe, skip"
fi

# ── BLOQUE 3: CPU GOVERNOR ────────────────────────────────────────────────────
log "CPU: Configurando CPU governor a performance..."

# Configurar todos los cores a performance para máximo rendimiento AI
for cpu_dir in /sys/devices/system/cpu/cpu[0-9]*; do
    if [[ -d "$cpu_dir" ]]; then
        gov_path="$cpu_dir/cpufreq/scaling_governor"
        if [[ -f "$gov_path" ]]; then
            CURRENT_GOV=$(cat "$gov_path" 2>/dev/null || echo "unknown")
            if [[ "$CURRENT_GOV" != "performance" ]]; then
                echo performance > "$gov_path" 2>/dev/null || true
            fi
        fi
    fi
done

# Verificar resultado
PERFORMANCE_COUNT=$(grep -l "performance" /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor 2>/dev/null | wc -l)
TOTAL_CPUS=$(nproc)
log "  CPU governor: $PERFORMANCE_COUNT/$TOTAL_CPUS cores en performance"

# ── BLOQUE 4: ULIMIT PARA UVICORN ────────────────────────────────────────────
log "ULIMIT: Configurando límites para uvicorn..."

# Configurar límites en systemd para el servicio viraclip
SYSTEMD_OVERRIDE_DIR="/etc/systemd/system/viraclip-backend.service.d"
if [[ ! -d "$SYSTEMD_OVERRIDE_DIR" ]]; then
    mkdir -p "$SYSTEMD_OVERRIDE_DIR"
fi

cat > "$SYSTEMD_OVERRIDE_DIR/limits.conf" << 'EOF'
[Service]
LimitNOFILE=2097152
LimitNPROC=65536
LimitMEMLOCK=infinity
EOF

log "  systemd limits: LimitNOFILE=2097152, LimitNPROC=65536 creados"
systemctl daemon-reload 2>/dev/null || log "  systemctl daemon-reload ejecutado"

# También configurar para el usuario actual en limits.conf
if ! grep -q "viraclip" /etc/security/limits.conf 2>/dev/null; then
    cat >> /etc/security/limits.conf << EOF

# ViraClip limits
$VIRACLIP_USER    soft    nofile    2097152
$VIRACLIP_USER    hard    nofile    2097152
$VIRACLIP_USER    soft    nproc     65536
$VIRACLIP_USER    hard    nproc     65536
EOF
    log "  /etc/security/limits.conf: Añadidos límites para $VIRACLIP_USER"
else
    log "  /etc/security/limits.conf: Límites ya configurados, skip"
fi

# ── BLOQUE 5: NVIDIA PERSISTENCE MODE ─────────────────────────────────────────
log "GPU: Verificando NVIDIA persistence mode..."

if command -v nvidia-smi &>/dev/null; then
    # Verificar si hay GPUs NVIDIA
    GPU_COUNT=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | wc -l)
    if [[ "$GPU_COUNT" -gt 0 ]]; then
        # Activar persistence mode
        nvidia-smi -pm 1 2>/dev/null || log "  WARN: nvidia-smi -pm 1 falló (puede ser Optimus)"
        
        # Configurar nvidia-persistenced service
        if command -v nvidia-persistenced &>/dev/null; then
            if ! systemctl is-enabled nvidia-persistenced &>/dev/null; then
                systemctl enable nvidia-persistenced 2>/dev/null || log "  nvidia-persistenced: no se pudo enable"
                systemctl start nvidia-persistenced 2>/dev/null || log "  nvidia-persistenced: no se pudo start"
            fi
        fi
        
        # Verificar estado
        PERSISTENCE_STATUS=$(nvidia-smi --query-gpu=persistence_mode --format=csv,noheader 2>/dev/null | head -1 | tr -d ' ')
        if [[ "$PERSISTENCE_STATUS" == "Enabled" ]]; then
            log "  NVIDIA persistence mode: Enabled ✓"
        else
            log "  NVIDIA persistence mode: $PERSISTENCE_STATUS (puede requerir reboot)"
        fi
        
        # Desactivar auto-boost para clocks más estables
        nvidia-smi --auto-boost-default=0 2>/dev/null || true
        log "  NVIDIA auto-boost: disabled"
        
        # Mostrar info de GPU
        GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
        GPU_TEMP=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader 2>/dev/null | head -1)
        log "  GPU: $GPU_NAME, Temp: ${GPU_TEMP}°C"
    else
        log "  WARN: No se detectaron GPUs NVIDIA"
    fi
else
    log "  WARN: nvidia-smi no encontrado"
fi

# ── BLOQUE 6: I/O SCHEDULER PARA NVME/SSD ───────────────────────────────────
log "I/O: Configurando scheduler para discos..."

for disk in /sys/block/nvme* /sys/block/sd*; do
    if [[ -d "$disk" ]]; then
        SCHEDULER_PATH="$disk/queue/scheduler"
        if [[ -f "$SCHEDULER_PATH" ]]; then
            DISK_NAME=$(basename "$disk")
            # Para NVMe: 'none' es óptimo (hardware gestiona mejor)
            # Para SATA SSD: 'mq-deadline' o 'kyber'
            if [[ "$DISK_NAME" == nvme* ]]; then
                echo none > "$SCHEDULER_PATH" 2>/dev/null || true
                log "  $DISK_NAME: scheduler → none (NVMe)"
            else
                echo mq-deadline > "$SCHEDULER_PATH" 2>/dev/null || true
                log "  $DISK_NAME: scheduler → mq-deadline"
            fi
            
            # Reducir read_ahead para NVMe
            echo 0 > "$disk/queue/read_ahead_kb" 2>/dev/null || true
        fi
    fi
done

# ── BLOQUE 7: VERIFICACIÓN FINAL ─────────────────────────────────────────────
log ""
log "=== RESUMEN POST-TUNING ==="
log "vm.swappiness:       $(cat /proc/sys/vm/swappiness)"
log "net.core.somaxconn:  $(cat /proc/sys/net/core/somaxconn)"
log "fs.file-max:         $(cat /proc/sys/fs/file-max)"
log "vm.dirty_ratio:      $(cat /proc/sys/vm/dirty_ratio)"
log ""
log "CPU cores performance: $(grep -c "performance" /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor 2>/dev/null || echo "0")/$(nproc)"
log ""
log "THP: $(cat /sys/kernel/mm/transparent_hugepage/enabled 2>/dev/null | grep -oP '\[\K[^\]]+' || echo "N/A")"
log ""

if command -v nvidia-smi &>/dev/null; then
    nvidia-smi --query-gpu=name,persistence_mode,temperature.gpu,power.draw --format=csv,noheader 2>/dev/null | while read line; do
        log "GPU: $line"
    done
fi

log ""
log "=== ViraClip Host Tuning DONE ==="
log ""
log "NOTAS:"
log "- Algunos cambios requieren reboot para ser permanentes (THP, GRUB)"
log "- Ejecutar 'sudo update-grub' si se modificó /etc/default/grub"
log "- Los límites ulimit aplican a nuevas sesiones (re-login necesario)"
log ""
log "SIGUIENTE: systemctl start viraclip-backend o docker-compose up -d"
