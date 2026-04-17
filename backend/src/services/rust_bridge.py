"""
Python-Rust communication bridge.

Calls the Rust agent HTTP API for performance-critical tasks.
"""

import httpx
import logging
from typing import Optional, Dict, Any, List
from ..config import get_config

logger = logging.getLogger(__name__)


class RustAgentBridge:
    """Bridge to communicate with Rust agent microservice."""
    
    def __init__(self):
        config = get_config()
        self.base_url = config.rust_agent_url or "http://rust-agent:8001"
        self.timeout = httpx.Timeout(300.0, connect=10.0)
    
    async def health_check(self) -> bool:
        """Check if Rust agent is healthy."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/agent/health")
                return response.status_code == 200
        except Exception as e:
            logger.warning(f"Rust agent health check failed: {e}")
            return False
    
    async def render_clip(
        self,
        input_path: str,
        output_path: str,
        start: str,
        end: str,
        use_gpu: bool = True
    ) -> Dict[str, Any]:
        """
        Render video clip using Rust agent's FFmpeg tool.
        
        Args:
            input_path: Source video path
            output_path: Output clip path
            start: Start timestamp (MM:SS)
            end: End timestamp (MM:SS)
            use_gpu: Use h264_nvenc GPU encoding
            
        Returns:
            Agent response with render result
        """
        logger.info(f"🦀 Rust agent rendering: {start} - {end}")
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/agent/run",
                    json={
                        "task": "render video clip",
                        "context": {
                            "input": input_path,
                            "output": output_path,
                            "start": start,
                            "end": end,
                            "codec": "h264_nvenc" if use_gpu else "libx264",
                            "use_gpu": use_gpu
                        },
                        "max_iterations": 1
                    }
                )
                response.raise_for_status()
                result = response.json()
                
                if result.get("success"):
                    logger.info(f"✅ Rust render complete: {output_path}")
                else:
                    logger.error(f"❌ Rust render failed: {result.get('error')}")
                
                return result
                
        except httpx.TimeoutException:
            logger.error(f"⏱️  Rust agent timeout rendering {output_path}")
            raise
        except Exception as e:
            logger.error(f"❌ Rust agent error: {e}")
            raise
    
    async def run_bash_command(
        self,
        command: str,
        timeout: int = 120000
    ) -> str:
        """
        Execute bash command via Rust agent (with whitelist validation).
        
        Args:
            command: Bash command to execute
            timeout: Timeout in milliseconds
            
        Returns:
            Command output
        """
        logger.info(f"🐚 Rust agent bash: {command}")
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/agent/run",
                    json={
                        "task": "execute bash command",
                        "context": {
                            "command": command,
                            "timeout": timeout
                        },
                        "max_iterations": 1
                    }
                )
                response.raise_for_status()
                result = response.json()
                
                if result.get("success"):
                    return result.get("result", "")
                else:
                    raise RuntimeError(result.get("error", "Unknown error"))
                    
        except Exception as e:
            logger.error(f"❌ Bash command failed: {e}")
            raise
    
    async def find_clips(
        self,
        pattern: str = "*.mp4",
        directory: str = "/app/temp/uploads/clips"
    ) -> List[str]:
        """
        Find clips matching pattern using Rust agent's glob tool.
        
        Args:
            pattern: Glob pattern
            directory: Directory to search
            
        Returns:
            List of matching file paths
        """
        logger.info(f"🔍 Rust agent glob: {pattern}")
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/agent/run",
                    json={
                        "task": "find files matching pattern",
                        "context": {
                            "pattern": pattern,
                            "directory": directory
                        },
                        "max_iterations": 1
                    }
                )
                response.raise_for_status()
                result = response.json()
                
                if result.get("success"):
                    output = result.get("result", "")
                    # Parse file paths from output
                    lines = output.split("\n")
                    files = [line.strip() for line in lines if line.strip() and "/" in line]
                    return files
                else:
                    return []
                    
        except Exception as e:
            logger.error(f"❌ Glob search failed: {e}")
            return []
    
    async def get_diagnostics(self) -> Dict[str, Any]:
        """
        Get system diagnostics from Rust agent.
        
        Returns:
            Diagnostics report
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.base_url}/agent/run",
                    json={
                        "task": "run system diagnostics",
                        "context": {},
                        "max_iterations": 1
                    }
                )
                response.raise_for_status()
                result = response.json()
                
                return {
                    "success": result.get("success", False),
                    "report": result.get("result", ""),
                    "tools_used": result.get("tools_used", [])
                }
                
        except Exception as e:
            logger.error(f"❌ Diagnostics failed: {e}")
            return {
                "success": False,
                "report": f"Error: {e}",
                "tools_used": []
            }


# Singleton instance
_rust_bridge: Optional[RustAgentBridge] = None


def get_rust_bridge() -> RustAgentBridge:
    """Get or create Rust bridge singleton."""
    global _rust_bridge
    if _rust_bridge is None:
        _rust_bridge = RustAgentBridge()
    return _rust_bridge
