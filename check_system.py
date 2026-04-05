#!/usr/bin/env python3
"""
ViraClip System Health Check
Cross-platform diagnostic script to verify all services are running correctly.

Usage:
  python check_system.py
  python check_system.py --docker-only  # Only check Docker services
  python check_system.py --verbose      # Show detailed output
"""

import subprocess
import sys
import os
import time
from pathlib import Path
from typing import Tuple, Optional, List

# ANSI color codes (work on Windows 10+ with VT100 enabled)
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"
BOLD = "\033[1m"

def enable_windows_ansi():
    """Enable ANSI colors on Windows."""
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            pass

enable_windows_ansi()

def print_header(text: str):
    """Print section header."""
    print(f"\n{BOLD}{BLUE}{'=' * 60}{RESET}")
    print(f"{BOLD}{BLUE}{text}{RESET}")
    print(f"{BOLD}{BLUE}{'=' * 60}{RESET}")

def print_check(name: str, passed: bool, details: str = ""):
    """Print check result with color."""
    status = f"{GREEN}✅ PASS{RESET}" if passed else f"{RED}❌ FAIL{RESET}"
    print(f"{status} | {name}")
    if details:
        print(f"       {details}")

def run_command(cmd: List[str], timeout: int = 10) -> Tuple[bool, str, str]:
    """Run shell command and return (success, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "", "Command timeout"
    except FileNotFoundError:
        return False, "", f"Command not found: {cmd[0]}"
    except Exception as e:
        return False, "", str(e)

def check_docker_running() -> bool:
    """Check if Docker daemon is running."""
    success, stdout, _ = run_command(["docker", "version", "--format", "{{.Server.Version}}"])
    if success and stdout:
        print_check(f"Docker daemon running (v{stdout})", True)
        return True
    else:
        print_check("Docker daemon running", False, "Run: docker --version to verify installation")
        return False

def check_docker_compose() -> bool:
    """Check if docker-compose is available."""
    success, stdout, _ = run_command(["docker-compose", "--version"])
    if success:
        version = stdout.split()[2] if len(stdout.split()) > 2 else "unknown"
        print_check(f"docker-compose available (v{version})", True)
        return True
    else:
        print_check("docker-compose available", False, "Install docker-compose")
        return False

def check_containers_running() -> Tuple[bool, List[str]]:
    """Check if all ViraClip containers are running."""
    success, stdout, _ = run_command(["docker-compose", "ps", "--format", "json"])
    
    if not success:
        print_check("ViraClip containers status", False, "Run: docker-compose up -d")
        return False, []
    
    required_services = ["backend", "worker", "redis", "postgres", "frontend"]
    running_services = []
    issues = []
    
    # Parse docker-compose ps output
    try:
        import json
        containers = []
        if stdout.strip():
            # Try to parse as JSON array or newline-delimited JSON
            for line in stdout.strip().split('\n'):
                if line.strip():
                    try:
                        containers.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        
        for container in containers:
            service = container.get("Service", "")
            state = container.get("State", "")
            
            if service in required_services:
                if state == "running":
                    running_services.append(service)
                else:
                    issues.append(f"{service}: {state}")
    except Exception:
        # Fallback to text parsing
        success, stdout, _ = run_command(["docker-compose", "ps"])
        for service in required_services:
            if service in stdout and "Up" in stdout:
                running_services.append(service)
    
    all_running = len(running_services) >= len(required_services)
    
    if all_running:
        print_check(f"All containers running ({len(running_services)} services)", True)
    else:
        missing = set(required_services) - set(running_services)
        details = f"Missing or not running: {', '.join(missing)}" if missing else ', '.join(issues)
        print_check(f"All containers running", False, details)
    
    return all_running, running_services

def check_redis() -> bool:
    """Check if Redis is responding."""
    success, stdout, _ = run_command(["docker-compose", "exec", "-T", "redis", "redis-cli", "ping"])
    
    if success and "PONG" in stdout:
        print_check("Redis responding to PING", True)
        return True
    else:
        print_check("Redis responding to PING", False, "Redis not responding")
        return False

def check_postgres() -> bool:
    """Check if PostgreSQL is responding."""
    success, stdout, _ = run_command([
        "docker-compose", "exec", "-T", "postgres",
        "pg_isready", "-U", "viraclip"
    ])
    
    if success and "accepting connections" in stdout:
        print_check("PostgreSQL accepting connections", True)
        return True
    else:
        print_check("PostgreSQL accepting connections", False, "Database not ready")
        return False

def check_ollama() -> bool:
    """Check if Ollama is running and has models."""
    # Check if Ollama container is running
    success, stdout, _ = run_command(["docker-compose", "exec", "-T", "ollama", "ollama", "list"])
    
    if not success:
        print_check("Ollama service", False, "Ollama container not responding")
        return False
    
    # Check if models are loaded
    if stdout and len(stdout.strip().split('\n')) > 1:  # Header + at least 1 model
        model_count = len(stdout.strip().split('\n')) - 1
        print_check(f"Ollama has models loaded ({model_count} model(s))", True)
        return True
    else:
        print_check("Ollama has models loaded", False, 
                   "No models found. Run: docker-compose exec ollama ollama pull llama3.2")
        return False

def check_workers() -> bool:
    """Check if at least one worker is active."""
    success, stdout, _ = run_command(["docker-compose", "ps", "worker", "worker-2", "worker-3"])
    
    if success and "Up" in stdout:
        worker_count = stdout.count("Up")
        print_check(f"Workers active ({worker_count} worker(s))", True)
        return True
    else:
        print_check("Workers active", False, "No workers running")
        return False

def check_backend_health() -> bool:
    """Check if backend /api/health endpoint responds."""
    try:
        import urllib.request
        import json
        
        with urllib.request.urlopen("http://localhost:8000/api/health", timeout=5) as response:
            if response.status == 200:
                data = json.loads(response.read().decode())
                status = data.get("status", "unknown")
                print_check(f"Backend health endpoint (status: {status})", True)
                return True
    except Exception as e:
        print_check("Backend health endpoint", False, f"Not responding: {e}")
        return False
    
    return False

def check_env_variables() -> bool:
    """Check if critical environment variables are set."""
    env_file = Path(".env")
    
    if not env_file.exists():
        print_check(".env file exists", False, "Copy .env.example to .env")
        return False
    
    env_content = env_file.read_text()
    
    critical_vars = {
        "ASSEMBLY_AI_API_KEY": False,
        "GOOGLE_API_KEY": False,
        "OPENAI_API_KEY": False,
        "ANTHROPIC_API_KEY": False,
        "LLM": False,
    }
    
    for line in env_content.split('\n'):
        line = line.strip()
        if line and not line.startswith('#'):
            for var in critical_vars:
                if line.startswith(f"{var}="):
                    value = line.split('=', 1)[1].strip()
                    if value and value != "your_api_key_here":
                        critical_vars[var] = True
    
    # At least one LLM provider must be configured
    llm_configured = critical_vars["LLM"]
    has_llm_key = (
        critical_vars["GOOGLE_API_KEY"] or 
        critical_vars["OPENAI_API_KEY"] or 
        critical_vars["ANTHROPIC_API_KEY"]
    )
    has_assemblyai = critical_vars["ASSEMBLY_AI_API_KEY"]
    
    all_ok = llm_configured and (has_llm_key or "ollama" in env_content.lower()) and has_assemblyai
    
    if all_ok:
        print_check("Critical environment variables set", True)
    else:
        missing = []
        if not has_assemblyai:
            missing.append("ASSEMBLY_AI_API_KEY")
        if not llm_configured:
            missing.append("LLM")
        if not has_llm_key and "ollama" not in env_content.lower():
            missing.append("LLM API key (GOOGLE/OPENAI/ANTHROPIC or ollama)")
        
        print_check("Critical environment variables set", False, 
                   f"Missing or empty: {', '.join(missing)}")
    
    return all_ok

def check_volumes() -> bool:
    """Check if required volumes/directories exist."""
    required_dirs = [
        "temp/uploads",
        "temp/clips",
        "models",
    ]
    
    all_exist = True
    missing = []
    
    for dir_path in required_dirs:
        path = Path(dir_path)
        if not path.exists():
            all_exist = False
            missing.append(dir_path)
    
    if all_exist:
        print_check("Required directories exist", True)
    else:
        print_check("Required directories exist", False, 
                   f"Missing: {', '.join(missing)}. Run: mkdir -p {' '.join(required_dirs)}")
    
    return all_exist

def check_gpu_setup() -> Tuple[bool, str]:
    """Check GPU availability and configuration."""
    # Check for NVIDIA GPU
    success, stdout, _ = run_command(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], timeout=3)
    
    if success and stdout:
        gpu_name = stdout.split('\n')[0]
        print_check(f"NVIDIA GPU detected: {gpu_name}", True)
        return True, "nvidia"
    
    # Check for AMD GPU (Windows)
    if sys.platform == "win32":
        success, stdout, _ = run_command(["wmic", "path", "win32_VideoController", "get", "name"], timeout=3)
        if success and "AMD" in stdout:
            print_check("AMD GPU detected (CPU mode recommended)", True, 
                       "Set WHISPER_DEVICE=cpu in .env")
            return True, "amd"
    
    print_check("GPU detected", False, "No GPU found - using CPU mode (slower)")
    return False, "cpu"

def main():
    """Run all system checks."""
    verbose = "--verbose" in sys.argv
    docker_only = "--docker-only" in sys.argv
    
    print_header("🔍 ViraClip System Health Check")
    print(f"Platform: {sys.platform}")
    print(f"Working directory: {os.getcwd()}")
    
    results = {}
    
    # Section 1: Docker Infrastructure
    print_header("1️⃣ Docker Infrastructure")
    results["docker_running"] = check_docker_running()
    results["docker_compose"] = check_docker_compose()
    
    if results["docker_running"] and results["docker_compose"]:
        results["containers"], running = check_containers_running()
    else:
        print(f"{YELLOW}⚠️  Skipping container checks (Docker not available){RESET}")
        results["containers"] = False
    
    # Section 2: Service Health
    if results["containers"]:
        print_header("2️⃣ Service Health Checks")
        results["redis"] = check_redis()
        results["postgres"] = check_postgres()
        results["ollama"] = check_ollama()
        results["workers"] = check_workers()
        results["backend"] = check_backend_health()
    else:
        print(f"{YELLOW}⚠️  Skipping service checks (containers not running){RESET}")
    
    if docker_only:
        print_header("📊 Summary (Docker checks only)")
        passed = sum([results["docker_running"], results["docker_compose"], results["containers"]])
        total = 3
    else:
        # Section 3: Configuration
        print_header("3️⃣ Configuration Checks")
        results["env_vars"] = check_env_variables()
        results["volumes"] = check_volumes()
        
        # Section 4: Hardware
        print_header("4️⃣ Hardware Detection")
        gpu_found, gpu_type = check_gpu_setup()
        results["gpu"] = gpu_found
        
        # Summary
        print_header("📊 Health Check Summary")
        passed = sum(1 for v in results.values() if v is True)
        total = len(results)
    
    percentage = int((passed / total) * 100) if total > 0 else 0
    
    if percentage == 100:
        print(f"\n{GREEN}{BOLD}✅ All checks passed! ({passed}/{total}){RESET}")
        print(f"{GREEN}ViraClip is ready to process videos.{RESET}")
        return 0
    elif percentage >= 70:
        print(f"\n{YELLOW}{BOLD}⚠️  Most checks passed ({passed}/{total} - {percentage}%){RESET}")
        print(f"{YELLOW}ViraClip may work but some features might be limited.{RESET}")
        return 1
    else:
        print(f"\n{RED}{BOLD}❌ System checks failed ({passed}/{total} - {percentage}%){RESET}")
        print(f"{RED}ViraClip will not work correctly. Fix the issues above.{RESET}")
        return 2

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Check interrupted by user{RESET}")
        sys.exit(130)
