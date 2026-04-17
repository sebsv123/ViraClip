"""
Clean Logs Utility

Removes null bytes and control characters from log files that cause read errors.

Usage:
    python scripts/clean_logs.py log_file.log
    python scripts/clean_logs.py *.log  # Clean all logs
"""

import sys
from pathlib import Path
import re

def clean_log_file(file_path: Path) -> bool:
    """
    Clean a log file by removing null bytes and control characters.
    
    Args:
        file_path: Path to log file
        
    Returns:
        True if cleaned successfully
    """
    print(f"Cleaning: {file_path}")
    
    try:
        # Read file as binary first
        with open(file_path, 'rb') as f:
            content = f.read()
        
        # Remove null bytes
        content = content.replace(b'\x00', b'')
        
        # Decode to text
        try:
            text = content.decode('utf-8', errors='replace')
        except:
            text = content.decode('latin-1', errors='replace')
        
        # Remove other problematic control characters (keep newlines, tabs)
        text = re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]', '', text)
        
        # Write back
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(text)
        
        print(f"  ✅ Cleaned successfully")
        return True
        
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False


def main():
    """Clean log files from command line."""
    if len(sys.argv) < 2:
        print("Usage: python clean_logs.py log_file.log")
        print("\nExample:")
        print("  python clean_logs.py pipeline_output.log")
        print("  python clean_logs.py *.log")
        sys.exit(1)
    
    # Get all log files from arguments
    log_files = []
    for pattern in sys.argv[1:]:
        path = Path(pattern)
        if path.exists() and path.is_file():
            log_files.append(path)
        else:
            # Try glob pattern
            matches = list(Path('.').glob(pattern))
            log_files.extend(matches)
    
    if not log_files:
        print(f"❌ No log files found matching: {sys.argv[1:]}")
        sys.exit(1)
    
    print(f"\n🧹 Cleaning {len(log_files)} log file(s)...\n")
    
    success = 0
    for log_file in log_files:
        if clean_log_file(log_file):
            success += 1
    
    print(f"\n✅ Cleaned {success}/{len(log_files)} files")


if __name__ == "__main__":
    main()
