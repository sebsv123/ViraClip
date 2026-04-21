#!/usr/bin/env bash
# monitor.sh — ViraClip System Resource Monitor
# Monitors GPU, CPU, RAM, Disk I/O every 30s with alerting
# Usage: ./monitor.sh [foreground|background]
#   foreground: run once and exit
#   background: run as daemon with 30s loop (default)

set -euo pipefail

# Configuration
INTERVAL=30
LOG_DIR="/var/log/viraclip"
LOG_FILE="$LOG_DIR/monitor.log"
MAX_LOG_SIZE=$((10 * 1024 * 1024))  # 10MB rotation
GPU_ALERT_THRESHOLD=50  # Alert if GPU < 50% during active render

# Ensure log directory exists
mkdir -p "$LOG_DIR"

# Mode: foreground (single run) or background (daemon)
MODE="${1:-background}"

# Logging function with rotation
log() {
    local level="$1"
    local msg="$2"
    local timestamp=$(date '+%Y-%m-%dT%H:%M:%S')
    local log_line="[$timestamp] [$level] $msg"
    
    echo "$log_line"
    echo "$log_line" >> "$LOG_FILE"
    
    # Rotate log if too large
    if [[ -f "$LOG_FILE" && $(stat -f%z "$LOG_FILE" 2>/dev/null || stat -c%s "$LOG_FILE" 2>/dev/null || echo 0) -gt $MAX_LOG_SIZE ]]; then
        mv "$LOG_FILE" "$LOG_FILE.$(date +%Y%m%d_%H%M%S)"
        gzip "$LOG_FILE."* 2>/dev/null || true
        touch "$LOG_FILE"
    fi
}

# Get GPU utilization from nvidia-smi
get_gpu_stats() {
    if ! command -v nvidia-smi &>/dev/null; then
        echo "N/A|N/A|N/A|N/A"
        return
    fi
    
    local stats
    stats=$(nvidia-smi --query-gpu=utilization.gpu,utilization.memory,temperature.gpu,power.draw --format=csv,noheader,nounits 2>/dev/null | head -1)
    
    if [[ -z "$stats" ]]; then
        echo "0|0|0|0"
        return
    fi
    
    # Parse: "45, 30, 65, 125.50"
    echo "$stats" | sed 's/, /|/g'
}

# Get CPU usage
get_cpu_stats() {
    # Read /proc/stat for CPU usage
    local cpu_line=$(head -1 /proc/stat)
    # cpu  user nice system idle iowait irq softirq steal guest guest_nice
    read -ra cpu_arr <<< "$cpu_line"
    
    local user=${cpu_arr[1]:-0}
    local nice=${cpu_arr[2]:-0}
    local system=${cpu_arr[3]:-0}
    local idle=${cpu_arr[4]:-0}
    local iowait=${cpu_arr[5]:-0}
    local irq=${cpu_arr[6]:-0}
    local softirq=${cpu_arr[7]:-0}
    
    local total=$((user + nice + system + idle + iowait + irq + softirq))
    local used=$((user + nice + system + irq + softirq))
    
    if [[ $total -gt 0 ]]; then
        echo "$((used * 100 / total))"
    else
        echo "0"
    fi
}

# Get RAM usage
get_ram_stats() {
    local mem_info=$(free -m | grep "^Mem:")
    read -ra mem_arr <<< "$mem_info"
    
    local total=${mem_arr[1]:-1}
    local used=${mem_arr[2]:-0}
    local available=${mem_arr[6]:-0}
    
    if [[ $total -gt 0 ]]; then
        local pct=$((used * 100 / total))
        echo "${used}MB/${total}MB (${pct}%)"
    else
        echo "N/A"
    fi
}

# Get Disk I/O stats
get_disk_io() {
    local read_bytes=0
    local write_bytes=0
    
    # Read /proc/diskstats for primary disk
    if [[ -f /proc/diskstats ]]; then
        # Sum all NVMe and SD disks
        while read -r line; do
            read -ra io_arr <<< "$line"
            local dev_name="${io_arr[2]}"
            
            # Only count actual disks (nvme*, sd*, vd*), not partitions
            if [[ "$dev_name" =~ ^(nvme[0-9]+n[0-9]+|sd[a-z]+|vd[a-z]+)$ ]]; then
                local rbytes=$((io_arr[5] * 512))  # sectors * 512 bytes
                local wbytes=$((io_arr[9] * 512))
                read_bytes=$((read_bytes + rbytes))
                write_bytes=$((write_bytes + wbytes))
            fi
        done < /proc/diskstats
    fi
    
    # Convert to MB/s (approximate, since we don't have delta time)
    echo "R:$((read_bytes / 1024 / 1024))MB W:$((write_bytes / 1024 / 1024))MB"
}

# Check if render is active (looking for ffmpeg/uvicorn high CPU)
is_render_active() {
    local ffmpeg_count=$(pgrep -c ffmpeg 2>/dev/null || echo 0)
    local high_cpu_uvicorn=$(ps aux | grep -E "uvicorn|python" | awk '$3 > 50.0 {print $0}' | wc -l)
    
    # Consider render active if ffmpeg running OR uvicorn using >50% CPU
    if [[ $ffmpeg_count -gt 0 || $high_cpu_uvicorn -gt 0 ]]; then
        echo "yes"
    else
        echo "no"
    fi
}

# Alert if GPU underutilized during render
check_gpu_alert() {
    local gpu_util="$1"
    local render_active="$2"
    
    if [[ "$render_active" == "yes" && "$gpu_util" != "N/A" ]]; then
        if [[ $gpu_util -lt $GPU_ALERT_THRESHOLD ]]; then
            log "ALERT" "GPU utilization ${gpu_util}% < ${GPU_ALERT_THRESHOLD}% durante render activo!"
            log "ALERT" "Posible cuello de botella: Verificar CPU-bound (Whisper) o I/O wait"
        fi
    fi
}

# Main monitoring iteration
monitor_iteration() {
    local timestamp=$(date '+%Y-%m-%dT%H:%M:%S')
    
    # Get stats
    IFS='|' read -r gpu_util gpu_mem gpu_temp gpu_power <<< "$(get_gpu_stats)"
    local cpu_util=$(get_cpu_stats)
    local ram_stats=$(get_ram_stats)
    local disk_io=$(get_disk_io)
    local render_active=$(is_render_active)
    
    # Format log line
    local stats_line="GPU:${gpu_util}%|${gpu_mem}%|${gpu_temp}°C|${gpu_power}W CPU:${cpu_util}% RAM:${ram_stats} IO:${disk_io} RENDER:${render_active}"
    
    log "INFO" "$stats_line"
    
    # Check for alerts
    if command -v nvidia-smi &>/dev/null; then
        check_gpu_alert "$gpu_util" "$render_active"
    fi
    
    # Memory pressure alert
    local mem_pct=$(echo "$ram_stats" | grep -oP '\d+(?=%)' || echo 0)
    if [[ $mem_pct -gt 90 ]]; then
        log "WARN" "Memoria crítica: ${ram_stats}"
    fi
    
    # Temperature alert
    if [[ "$gpu_temp" != "N/A" && "$gpu_temp" != "" ]]; then
        if [[ $gpu_temp -gt 85 ]]; then
            log "WARN" "GPU temperatura alta: ${gpu_temp}°C"
        fi
    fi
}

# Print header
log "INFO" "=== ViraClip Monitor START (interval: ${INTERVAL}s) ==="
log "INFO" "Log file: $LOG_FILE"
log "INFO" "GPU alert threshold: ${GPU_ALERT_THRESHOLD}% (during active render)"

# Main loop
if [[ "$MODE" == "foreground" ]]; then
    # Single run mode
    monitor_iteration
    log "INFO" "=== ViraClip Monitor SINGLE RUN DONE ==="
else
    # Background daemon mode
    log "INFO" "Running in background mode. Press Ctrl+C to stop."
    
    # Trap signals for graceful shutdown
    trap 'log "INFO" "=== ViraClip Monitor STOPPED ==="; exit 0' SIGINT SIGTERM
    
    while true; do
        monitor_iteration
        sleep "$INTERVAL"
    done
fi
