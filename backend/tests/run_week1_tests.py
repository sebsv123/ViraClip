"""
Quick test runner for Week 1 Foundation features.

Run from backend directory:
    python -m pytest tests/test_week1_foundation.py -v
    
Or run this file directly:
    python tests/run_week1_tests.py
"""

import subprocess
import sys
from pathlib import Path


def run_tests():
    """Run Week 1 foundation tests with coverage."""
    
    backend_dir = Path(__file__).parent.parent
    test_file = backend_dir / "tests" / "test_week1_foundation.py"
    
    print("=" * 70)
    print("🧪 Running Week 1 Foundation Tests")
    print("=" * 70)
    print()
    
    # Run pytest with coverage
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(test_file),
        "-v",
        "--tb=short",
        "--color=yes",
        "-x",  # Stop on first failure
    ]
    
    print(f"Command: {' '.join(cmd)}")
    print()
    
    result = subprocess.run(cmd, cwd=str(backend_dir))
    
    print()
    print("=" * 70)
    if result.returncode == 0:
        print("✅ All tests passed!")
    else:
        print(f"❌ Tests failed with exit code {result.returncode}")
    print("=" * 70)
    
    return result.returncode


if __name__ == "__main__":
    exit_code = run_tests()
    sys.exit(exit_code)
