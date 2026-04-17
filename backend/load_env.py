"""
Environment Variable Loader for Direct Python Execution

Use this when running Python scripts directly (outside Docker) to ensure
.env variables are loaded properly.

Usage:
    python load_env.py script_name.py
    
Or in your script:
    from load_env import ensure_env_loaded
    ensure_env_loaded()
"""

import os
from pathlib import Path
from dotenv import load_dotenv
import sys

def ensure_env_loaded(env_file: str = None):
    """
    Ensure .env file is loaded before running scripts.
    
    Args:
        env_file: Path to .env file (defaults to repo root .env)
    """
    if env_file is None:
        # Find .env in repo root
        current = Path(__file__).resolve()
        repo_root = current.parent.parent  # backend/ -> ViraClip/
        env_file = repo_root / ".env"
    
    env_path = Path(env_file)
    
    if not env_path.exists():
        print(f"⚠️  WARNING: .env file not found at {env_path}")
        print(f"   Copy .env.example to .env and configure your API keys")
        return False
    
    # Load .env
    load_dotenv(env_path, override=True)
    print(f"✅ Loaded environment from: {env_path}")
    
    # Validate critical keys
    critical_keys = ["GROQ_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"]
    has_llm = any(os.getenv(key) for key in critical_keys)
    
    if not has_llm:
        print(f"⚠️  WARNING: No LLM API key found!")
        print(f"   Set at least one of: {', '.join(critical_keys)}")
        print(f"   Pipeline will use fallback text-based analysis (lower quality)")
    else:
        found_keys = [key for key in critical_keys if os.getenv(key)]
        print(f"✅ LLM API keys found: {', '.join(found_keys)}")
    
    return True


if __name__ == "__main__":
    # FIX Bug #7: Load .env and run a script
    if len(sys.argv) < 2:
        print("Usage: python load_env.py script_name.py [args...]")
        print("\nExample:")
        print("  python load_env.py viraclip_pipeline.py")
        print("  python load_env.py scripts/test_image_providers.py")
        sys.exit(1)
    
    # Load environment
    ensure_env_loaded()
    
    # Run the target script
    script_path = sys.argv[1]
    script_args = sys.argv[2:]
    
    if not os.path.exists(script_path):
        print(f"❌ Script not found: {script_path}")
        sys.exit(1)
    
    print(f"\n🚀 Running: {script_path} {' '.join(script_args)}\n")
    print("=" * 70)
    
    # Execute script with remaining args
    sys.argv = [script_path] + script_args
    with open(script_path) as f:
        code = compile(f.read(), script_path, 'exec')
        exec(code, {'__name__': '__main__', '__file__': script_path})
