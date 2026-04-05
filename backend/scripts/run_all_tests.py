"""
run_all_tests.py — ViraClip Test Suite Runner
==============================================
Ejecuta todos los tests de todas las phases implementadas.
Útil para CI/CD, pre-deployment verification, y regression testing.

Usage (PowerShell):
    # Dentro del container
    docker-compose exec backend python /app/scripts/run_all_tests.py

    # Con coverage report
    docker-compose exec backend python /app/scripts/run_all_tests.py --coverage

    # Solo tests rápidos (unit, sin integration)
    docker-compose exec backend python /app/scripts/run_all_tests.py --fast

    # Solo una phase específica
    docker-compose exec backend python /app/scripts/run_all_tests.py --phase 2.2

Exit codes:
    0 = todos los tests pasaron
    1 = algún test falló
    2 = error de configuración
"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

# Test files por phase (orden de ejecución)
TEST_PHASES = {
    "2.2": ["test_phase_2_2_viral_scorer.py"],
    "2.3": ["test_phase_2_3_transitions.py"],
    "3.5": ["test_phase_3_5_hook_slowmo.py"],
    "8.3": ["test_phase_8_3_engagement.py"],
    "8.4": ["test_phase_8_4_onnx.py"],
}

# Tests core (siempre se ejecutan)
CORE_TESTS = [
    # Aquí se pueden agregar tests de infraestructura base
    # Por ahora solo tenemos tests de phases específicas
]


def run_pytest(
    test_files: List[str],
    coverage: bool = False,
    verbose: bool = True,
    fast: bool = False,
) -> Tuple[int, str]:
    """
    Ejecuta pytest con los archivos especificados.
    
    Returns:
        (exit_code, output_summary)
    """
    cmd = ["pytest"]
    
    if verbose:
        cmd.append("-v")
    
    if fast:
        cmd.extend(["-m", "not slow"])  # Skip tests marcados como @pytest.mark.slow
    
    if coverage:
        cmd.extend([
            "--cov=src",
            "--cov-report=term-missing",
            "--cov-report=html:htmlcov",
        ])
    
    # Agregar archivos de test
    for tf in test_files:
        test_path = Path("/app/tests") / tf
        if test_path.exists():
            cmd.append(str(test_path))
        else:
            print(f"⚠ Test file not found: {tf}")
    
    if len(cmd) == 1:  # Solo 'pytest', sin archivos
        return 2, "No test files found"
    
    print(f"\n{'='*60}")
    print(f"Running: {' '.join(cmd)}")
    print(f"{'='*60}\n")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 min timeout
        )
        
        # Mostrar output
        print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr, file=sys.stderr)
        
        # Parse summary
        lines = result.stdout.split("\n")
        summary = "Unknown"
        for line in reversed(lines):
            if "passed" in line or "failed" in line or "error" in line:
                summary = line.strip()
                break
        
        return result.returncode, summary
        
    except subprocess.TimeoutExpired:
        return 1, "TIMEOUT (>10min)"
    except Exception as e:
        return 1, f"ERROR: {e}"


def main():
    parser = argparse.ArgumentParser(
        description="Run ViraClip test suite (all phases)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--phase",
        help="Run only tests for specific phase (e.g., '2.2', '8.3')",
    )
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="Generate coverage report (slower)",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Skip slow integration tests",
    )
    parser.add_argument(
        "--list-phases",
        action="store_true",
        help="List available test phases and exit",
    )
    args = parser.parse_args()
    
    if args.list_phases:
        print("\n📋 Available test phases:")
        for phase, files in sorted(TEST_PHASES.items()):
            print(f"   Phase {phase}: {len(files)} test file(s)")
            for f in files:
                print(f"      - {f}")
        print()
        return 0
    
    # Determinar qué tests ejecutar
    test_files = []
    phases_to_run = []
    
    if args.phase:
        if args.phase not in TEST_PHASES:
            print(f"❌ Unknown phase: {args.phase}")
            print(f"   Available: {', '.join(sorted(TEST_PHASES.keys()))}")
            return 2
        test_files.extend(TEST_PHASES[args.phase])
        phases_to_run.append(args.phase)
    else:
        # Ejecutar todos
        test_files.extend(CORE_TESTS)
        for phase in sorted(TEST_PHASES.keys()):
            test_files.extend(TEST_PHASES[phase])
            phases_to_run.append(phase)
    
    print("\n" + "="*60)
    print("🧪 ViraClip Test Suite")
    print("="*60)
    print(f"Phases: {', '.join(phases_to_run) if phases_to_run else 'Core only'}")
    print(f"Total test files: {len(test_files)}")
    print(f"Coverage: {'Yes' if args.coverage else 'No'}")
    print(f"Fast mode: {'Yes' if args.fast else 'No'}")
    print("="*60 + "\n")
    
    # Ejecutar
    exit_code, summary = run_pytest(
        test_files,
        coverage=args.coverage,
        fast=args.fast,
    )
    
    # Resumen final
    print("\n" + "="*60)
    if exit_code == 0:
        print("✅ ALL TESTS PASSED")
    else:
        print("❌ SOME TESTS FAILED")
    print(f"Summary: {summary}")
    print("="*60 + "\n")
    
    if args.coverage and exit_code == 0:
        print("📊 Coverage report: /app/htmlcov/index.html\n")
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
