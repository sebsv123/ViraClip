"""
Environment Validation Script

Validates that ViraClip environment is properly configured before startup.
Checks: directories, environment variables, models, dependencies.

Usage:
    python scripts/validate_environment.py
    python scripts/validate_environment.py --fix  # Auto-create missing dirs
"""

import os
import sys
from pathlib import Path
import subprocess

# Colors for output
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    END = '\033[0m'
    BOLD = '\033[1m'

def print_header(text):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*70}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{text}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*70}{Colors.END}\n")

def print_success(text):
    print(f"{Colors.GREEN}✅ {text}{Colors.END}")

def print_warning(text):
    print(f"{Colors.YELLOW}⚠️  {text}{Colors.END}")

def print_error(text):
    print(f"{Colors.RED}❌ {text}{Colors.END}")

def print_info(text):
    print(f"{Colors.BLUE}ℹ️  {text}{Colors.END}")


def check_directories(fix=False):
    """Check and optionally create required directories."""
    print_header("1. Checking Required Directories")
    
    # Get base paths
    if os.path.exists("/app"):
        base = Path("/app")  # Docker
    else:
        base = Path(__file__).parent.parent.parent  # Standalone
    
    required_dirs = [
        base / "temp" / "uploads",
        base / "temp" / "uploads" / "clips",
        base / "temp" / "uploads" / "downloads",
        base / "storage" / "overlay_cache",
        base / "models",
        base / "datasets",
        base / "data" / "reasoning_traces",
        base / "assets" / "sounds",
        base / "fonts",
        base / "transitions",
    ]
    
    issues = 0
    for directory in required_dirs:
        if directory.exists():
            print_success(f"{directory.relative_to(base) if directory.is_relative_to(base) else directory}")
        else:
            if fix:
                try:
                    directory.mkdir(parents=True, exist_ok=True)
                    print_success(f"{directory.relative_to(base) if directory.is_relative_to(base) else directory} (created)")
                except Exception as e:
                    print_error(f"{directory}: Failed to create - {e}")
                    issues += 1
            else:
                print_warning(f"{directory}: Missing (use --fix to create)")
                issues += 1
    
    return issues


def check_environment_variables():
    """Check critical environment variables."""
    print_header("2. Checking Environment Variables")
    
    # Critical for basic operation
    critical_vars = {
        "DATABASE_URL": "Database connection",
        "REDIS_HOST": "Redis cache",
    }
    
    # At least one LLM provider needed
    llm_providers = {
        "GROQ_API_KEY": "Groq (recommended, free)",
        "OPENAI_API_KEY": "OpenAI GPT",
        "GOOGLE_API_KEY": "Google Gemini",
        "ANTHROPIC_API_KEY": "Anthropic Claude",
    }
    
    # Optional but recommended
    optional_vars = {
        "PEXELS_API_KEY": "Stock photos/videos",
        "PIXABAY_API_KEY": "Additional stock media",
        "ASSEMBLY_AI_API_KEY": "Enhanced transcription",
    }
    
    issues = 0
    
    # Check critical
    print(f"\n{Colors.BOLD}Critical Variables:{Colors.END}")
    for var, desc in critical_vars.items():
        value = os.getenv(var)
        if value:
            # Mask sensitive values
            masked = value[:8] + "..." if len(value) > 8 else "***"
            print_success(f"{var}: {masked} ({desc})")
        else:
            print_error(f"{var}: Missing! ({desc})")
            issues += 1
    
    # Check LLM providers
    print(f"\n{Colors.BOLD}LLM Providers (need at least one):{Colors.END}")
    llm_found = False
    for var, desc in llm_providers.items():
        value = os.getenv(var)
        if value:
            masked = value[:8] + "..."
            print_success(f"{var}: {masked} ({desc})")
            llm_found = True
        else:
            print_info(f"{var}: Not set ({desc})")
    
    if not llm_found:
        print_warning("No LLM API key found! Pipeline will use fallback text analysis (lower quality)")
        print_info("Set at least one: GROQ_API_KEY (recommended), OPENAI_API_KEY, GOOGLE_API_KEY, or ANTHROPIC_API_KEY")
        issues += 1
    
    # Check optional
    print(f"\n{Colors.BOLD}Optional (Recommended):{Colors.END}")
    for var, desc in optional_vars.items():
        value = os.getenv(var)
        if value:
            print_success(f"{var}: Set ({desc})")
        else:
            print_info(f"{var}: Not set ({desc})")
    
    return issues


def check_whisper_config():
    """Check Whisper configuration."""
    print_header("3. Checking Whisper Configuration")
    
    device = os.getenv("WHISPER_DEVICE", "cpu")
    model_size = os.getenv("WHISPER_MODEL_SIZE", "medium")
    compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
    
    print(f"Device: {device}")
    print(f"Model Size: {model_size}")
    print(f"Compute Type: {compute_type}")
    
    if device == "cuda":
        print_warning("CUDA device selected - ensure GPU and CUDA are properly installed")
        print_info("If CUDA fails, set WHISPER_DEVICE=cpu in .env")
    else:
        print_success("Using CPU (safe default)")
    
    return 0


def check_docker_services():
    """Check if Docker services are running (if in Docker environment)."""
    print_header("4. Checking Docker Services")
    
    if not os.path.exists("/.dockerenv"):
        print_info("Not running in Docker container (skipping service check)")
        return 0
    
    services_to_check = [
        ("postgres:5432", "PostgreSQL database"),
        ("redis:6379", "Redis cache"),
        ("ollama:11434", "Ollama LLM"),
    ]
    
    issues = 0
    for host_port, desc in services_to_check:
        host, port = host_port.split(":")
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((host, int(port)))
            sock.close()
            
            if result == 0:
                print_success(f"{desc} ({host}:{port})")
            else:
                print_warning(f"{desc} ({host}:{port}): Not reachable")
                issues += 1
        except Exception as e:
            print_warning(f"{desc}: Check failed - {e}")
            issues += 1
    
    return issues


def check_python_dependencies():
    """Check critical Python packages."""
    print_header("5. Checking Python Dependencies")
    
    critical_packages = [
        "fastapi",
        "uvicorn",
        "pydantic",
        "sqlalchemy",
        "redis",
        "httpx",
        "pydantic_ai",
    ]
    
    issues = 0
    for package in critical_packages:
        try:
            __import__(package)
            print_success(f"{package}")
        except ImportError:
            print_error(f"{package}: Not installed")
            issues += 1
    
    return issues


def main():
    """Run all validation checks."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Validate ViraClip environment')
    parser.add_argument('--fix', action='store_true', help='Auto-create missing directories')
    args = parser.parse_args()
    
    print(f"\n{Colors.BOLD}🔍 ViraClip Environment Validation{Colors.END}\n")
    
    total_issues = 0
    
    # Run all checks
    total_issues += check_directories(fix=args.fix)
    total_issues += check_environment_variables()
    total_issues += check_whisper_config()
    total_issues += check_docker_services()
    total_issues += check_python_dependencies()
    
    # Summary
    print_header("Summary")
    
    if total_issues == 0:
        print_success("All checks passed! Environment is properly configured ✅")
        return 0
    else:
        print_warning(f"Found {total_issues} issue(s) that need attention")
        print_info("Fix issues and run validation again")
        return 1


if __name__ == "__main__":
    sys.exit(main())
