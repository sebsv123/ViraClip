#!/usr/bin/env python3
"""
Test B-roll Provider Strategy - Validates premium-first ordering and quality gate.

EXECUTION:
    cd /home/_sebastian/CascadeProjects/ViraClip/backend
    python3 test_broll_strategy.py
    
    OR as module (proper package context):
    python3 -m backend.test_broll_strategy
"""
import os
import sys

# Add src to path for standalone execution
backend_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(backend_dir, 'src')
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

# Set test environment
os.environ.setdefault('BROLL_PROVIDER_PRIORITY', 'premium_first')
os.environ.setdefault('BROLL_ENABLE_PREMIUM', 'true')
os.environ.setdefault('BROLL_ENABLE_STOCK', 'true')

from services.broll_provider_strategy import (
    BROLL_PROVIDER_PRIORITY,
    BROLL_ENABLE_PREMIUM,
    BROLL_ENABLE_STOCK,
    ProviderType,
    get_provider_order,
    get_provider_order_labels,
    diagnose_providers,
    passes_quality_gate,
)

def test_provider_priority():
    """Test that premium providers come before stock."""
    print("\n=== TEST 1: Provider Priority ===")
    order = get_provider_order_labels()
    print(f"Provider order: {order}")
    
    # Find positions
    ltxv_pos = order.index('ltxv') if 'ltxv' in order else -1
    stock_pos = order.index('stock_video') if 'stock_video' in order else -1
    
    if ltxv_pos < stock_pos:
        print(f"✅ PASS: LTXV (pos {ltxv_pos}) comes before stock_video (pos {stock_pos})")
        return True
    else:
        print(f"❌ FAIL: stock_video (pos {stock_pos}) comes before LTXV (pos {ltxv_pos})")
        return False

def test_high_priority_skips_image():
    """Test that HIGH priority excludes image fallback."""
    print("\n=== TEST 2: HIGH Priority Excludes Image ===")
    normal_order = get_provider_order_labels('NORMAL')
    high_order = get_provider_order_labels('HIGH')
    
    print(f"NORMAL order: {normal_order}")
    print(f"HIGH order: {high_order}")
    
    if 'stock_image' in normal_order and 'stock_image' not in high_order:
        print("✅ PASS: HIGH priority excludes stock_image for video-only assets")
        return True
    else:
        print("❌ FAIL: HIGH priority should exclude stock_image")
        return False

def test_stock_first_mode():
    """Test stock_first mode reverses the order."""
    print("\n=== TEST 3: Stock-First Mode ===")
    os.environ['BROLL_PROVIDER_PRIORITY'] = 'stock_first'
    
    # Need to reimport to pick up new env var
    import importlib
    from services import broll_provider_strategy
    importlib.reload(broll_provider_strategy)
    
    order = broll_provider_strategy.get_provider_order_labels()
    print(f"Stock-first order: {order}")
    
    stock_pos = order.index('stock_video') if 'stock_video' in order else -1
    ltxv_pos = order.index('ltxv') if 'ltxv' in order else -1
    
    result = stock_pos < ltxv_pos
    if result:
        print(f"✅ PASS: stock_video (pos {stock_pos}) comes before LTXV (pos {ltxv_pos})")
    else:
        print(f"❌ FAIL: Expected stock before LTXV in stock_first mode")
    
    # Reset to premium_first
    os.environ['BROLL_PROVIDER_PRIORITY'] = 'premium_first'
    importlib.reload(broll_provider_strategy)
    return result

def test_diagnostics():
    """Test provider diagnostics."""
    print("\n=== TEST 4: Provider Diagnostics ===")
    try:
        status = diagnose_providers()
        print(f"Status: {status.as_dict()}")
        print("✅ PASS: Diagnostics run without errors")
        return True
    except Exception as e:
        print(f"❌ FAIL: Diagnostics failed: {e}")
        return False

def test_quality_gate_nonexistent():
    """Test quality gate rejects non-existent files."""
    print("\n=== TEST 5: Quality Gate - Non-existent File ===")
    from pathlib import Path
    result = passes_quality_gate(Path('/nonexistent/file.mp4'), 'test')
    if not result:
        print("✅ PASS: Quality gate correctly rejects non-existent file")
        return True
    else:
        print("❌ FAIL: Quality gate should reject non-existent files")
        return False

def main():
    print("=" * 60)
    print("B-roll Provider Strategy Test Suite")
    print(f"Python: {sys.executable}")
    print(f"CWD: {os.getcwd()}")
    print("=" * 60)
    
    results = [
        test_provider_priority(),
        test_high_priority_skips_image(),
        test_stock_first_mode(),
        test_diagnostics(),
        test_quality_gate_nonexistent(),
    ]
    
    print("\n" + "=" * 60)
    print(f"Results: {sum(results)}/{len(results)} tests passed")
    print("=" * 60)
    
    if all(results):
        print("✅ ALL TESTS PASSED")
        return 0
    else:
        print("❌ SOME TESTS FAILED")
        return 1

if __name__ == '__main__':
    sys.exit(main())
