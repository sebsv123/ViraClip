"""
Bundle Optimization and Lazy Loading Module
Optimizes memory usage and module loading for better performance.
"""

import sys
import importlib
from typing import Dict, Any, List, Optional, Callable
from functools import wraps
import logging

logger = logging.getLogger(__name__)


class LazyModuleLoader:
    """
    Lazy loader for heavy modules to reduce startup time and memory.
    """
    
    def __init__(self):
        self._loaded_modules: Dict[str, Any] = {}
        self._loading_hooks: Dict[str, List[Callable]] = {}
    
    def load(self, module_name: str, import_path: Optional[str] = None) -> Any:
        """
        Lazy load a module only when needed.
        
        Args:
            module_name: Name of the module to load
            import_path: Optional specific import path (e.g., 'package.submodule')
        """
        if module_name in self._loaded_modules:
            return self._loaded_modules[module_name]
        
        try:
            path = import_path or module_name
            module = importlib.import_module(path)
            self._loaded_modules[module_name] = module
            
            # Trigger hooks
            if module_name in self._loading_hooks:
                for hook in self._loading_hooks[module_name]:
                    try:
                        hook(module)
                    except Exception as e:
                        logger.warning(f"Loading hook error for {module_name}: {e}")
            
            logger.debug(f"Lazy loaded module: {module_name}")
            return module
            
        except ImportError as e:
            logger.error(f"Failed to load module {module_name}: {e}")
            raise
    
    def register_hook(self, module_name: str, hook: Callable) -> None:
        """Register a hook to run when module is loaded."""
        if module_name not in self._loading_hooks:
            self._loading_hooks[module_name] = []
        self._loading_hooks[module_name].append(hook)
    
    def is_loaded(self, module_name: str) -> bool:
        """Check if a module has been loaded."""
        return module_name in self._loaded_modules
    
    def unload(self, module_name: str) -> bool:
        """Unload a module to free memory."""
        if module_name in self._loaded_modules:
            del self._loaded_modules[module_name]
            # Remove from sys.modules to allow reimport
            if module_name in sys.modules:
                del sys.modules[module_name]
            logger.debug(f"Unloaded module: {module_name}")
            return True
        return False
    
    def get_memory_usage(self) -> Dict[str, int]:
        """Get estimated memory usage of loaded modules."""
        import sys
        
        sizes = {}
        for name, module in self._loaded_modules.items():
            # Estimate size by checking module dict size
            size = sys.getsizeof(module.__dict__)
            sizes[name] = size
        
        return sizes


class BundleOptimizer:
    """
    Optimizes application bundle and resource loading.
    """
    
    # Heavy modules that should be lazy loaded
    HEAVY_MODULES = {
        "moviepy": "moviepy.editor",
        "whisper": "faster_whisper",
        "torch": "torch",
        "transformers": "transformers",
        "cv2": "cv2",
        "mediapipe": "mediapipe",
        "numpy": "numpy",
        "scipy": "scipy",
    }
    
    def __init__(self):
        self.lazy_loader = LazyModuleLoader()
        self._optimization_enabled = True
    
    def setup_lazy_loading(self) -> None:
        """Configure lazy loading for heavy modules."""
        for alias, module_path in self.HEAVY_MODULES.items():
            # Register pre-loading hooks for optimization
            self.lazy_loader.register_hook(
                alias,
                self._optimize_module_loading
            )
        
        logger.info("Lazy loading configured for heavy modules")
    
    def _optimize_module_loading(self, module) -> None:
        """Optimization hook when a module is loaded."""
        # Apply module-specific optimizations
        module_name = getattr(module, '__name__', '')
        
        if 'moviepy' in module_name:
            # Configure moviepy for headless/batch processing
            if hasattr(module, 'config'):
                try:
                    module.config.ffmpeg_binary = "ffmpeg"
                    module.config.IMAGEMAGICK_BINARY = "convert"
                except:
                    pass
        
        elif 'torch' in module_name:
            # Configure torch for inference only
            import torch
            torch.set_num_threads(2)  # Limit thread usage
            torch.set_grad_enabled(False)  # Disable gradients
    
    def get_module(self, name: str) -> Any:
        """Get a module with lazy loading."""
        if name in self.HEAVY_MODULES:
            return self.lazy_loader.load(name, self.HEAVY_MODULES[name])
        return importlib.import_module(name)
    
    def optimize_memory(self) -> Dict[str, Any]:
        """Optimize memory usage by unloading unused modules."""
        unloaded = []
        memory_saved = 0
        
        # Check which modules haven't been used recently
        memory_usage = self.lazy_loader.get_memory_usage()
        
        for module_name, size in memory_usage.items():
            # Unload if module is heavy and not critical
            if module_name in self.HEAVY_MODULES and module_name not in ["numpy"]:
                if self.lazy_loader.unload(module_name):
                    unloaded.append(module_name)
                    memory_saved += size
        
        # Force garbage collection
        import gc
        gc.collect()
        
        return {
            "unloaded_modules": unloaded,
            "memory_saved_bytes": memory_saved,
            "remaining_modules": list(self.lazy_loader._loaded_modules.keys())
        }
    
    def get_bundle_stats(self) -> Dict[str, Any]:
        """Get bundle statistics."""
        loaded = list(self.lazy_loader._loaded_modules.keys())
        available = list(self.HEAVY_MODULES.keys())
        
        return {
            "loaded_modules": loaded,
            "available_modules": available,
            "lazy_load_percentage": (
                (len(available) - len(loaded)) / len(available) * 100
            ) if available else 0,
            "memory_usage": self.lazy_loader.get_memory_usage(),
            "optimization_enabled": self._optimization_enabled
        }


# Global instances
_lazy_loader: Optional[LazyModuleLoader] = None
_bundle_optimizer: Optional[BundleOptimizer] = None


def get_lazy_loader() -> LazyModuleLoader:
    """Get global lazy loader instance."""
    global _lazy_loader
    if _lazy_loader is None:
        _lazy_loader = LazyModuleLoader()
    return _lazy_loader


def get_bundle_optimizer() -> BundleOptimizer:
    """Get global bundle optimizer instance."""
    global _bundle_optimizer
    if _bundle_optimizer is None:
        _bundle_optimizer = BundleOptimizer()
    return _bundle_optimizer


# Decorator for lazy loading dependencies
def lazy_import(module_name: str, import_path: Optional[str] = None):
    """Decorator to lazy import heavy dependencies in functions."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Load module before execution
            loader = get_lazy_loader()
            module = loader.load(module_name, import_path)
            
            # Inject into kwargs if requested
            if f"_{module_name}" in func.__code__.co_varnames:
                kwargs[f"_{module_name}"] = module
            
            return func(*args, **kwargs)
        return wrapper
    return decorator


# Convenience functions
def load_heavy_module(name: str) -> Any:
    """Load a heavy module with lazy loading."""
    return get_bundle_optimizer().get_module(name)


def optimize_memory() -> Dict[str, Any]:
    """Optimize memory by unloading unused modules."""
    return get_bundle_optimizer().optimize_memory()


def get_memory_stats() -> Dict[str, Any]:
    """Get memory usage statistics."""
    return get_bundle_optimizer().get_bundle_stats()
