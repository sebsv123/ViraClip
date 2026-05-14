#!/usr/bin/env python3
"""Patch ComfyUI's model_management.py to force CPU-only mode.

This replaces the get_torch_device() function to always return cpu,
and patches all torch.cuda references to prevent CUDA init crashes
when using CPU-only PyTorch (e.g., on Blackwell RTX 5070).
"""
import re

with open('/comfyui/comfy/model_management.py', 'r') as f:
    content = f.read()

# 1. Replace the get_torch_device() function body to always return cpu
#    This avoids torch.cuda.current_device() which crashes on CPU-only PyTorch
old_get_device = '''def get_torch_device():
    """Get the device to use for PyTorch operations."""
    if torch.cuda.is_available():
        i = torch.cuda.current_device()
'''

new_get_device = '''def get_torch_device():
    """Get the device to use for PyTorch operations (CPU-only mode)."""
    return torch.device("cpu")
'''

if old_get_device in content:
    content = content.replace(old_get_device, new_get_device)
    print('Patched get_torch_device() to return cpu')
else:
    print('WARNING: Could not find get_torch_device() pattern, trying alternative...')
    # Fallback: try to find the function by line number
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if 'def get_torch_device()' in line:
            # Replace from this line until we find a line that's not indented (next function)
            start = i
            j = i + 1
            while j < len(lines) and (lines[j].startswith('    ') or lines[j].strip() == ''):
                j += 1
            # Replace with our CPU-only version
            lines[start:j] = ['def get_torch_device():', '    """Get the device to use for PyTorch operations (CPU-only mode)."""', '    return torch.device("cpu")', '']
            content = '\n'.join(lines)
            print(f'Patched get_torch_device() at line {i+1} via fallback')
            break

# 2. Also patch torch.cuda references that might be called at module level
#    (e.g., total_vram = get_total_memory(get_torch_device()))
#    These are already handled by the get_torch_device() patch above.

# 3. Patch any remaining torch.cuda calls that could crash at import time
#    Replace torch.cuda.is_available() with False
content = content.replace('torch.cuda.is_available()', 'False')
content = content.replace('torch.cuda.device_count()', '0')

with open('/comfyui/comfy/model_management.py', 'w') as f:
    f.write(content)

print('ComfyUI patched for CPU-only mode successfully')
