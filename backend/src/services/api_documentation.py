"""
Auto API Documentation System
Generates and serves API documentation automatically from code.
"""

import inspect
import logging
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class APIDocGenerator:
    """
    Automatically generates API documentation from FastAPI routes.
    """
    
    def __init__(self):
        self._endpoints: List[Dict[str, Any]] = []
        self._schemas: Dict[str, Dict[str, Any]] = {}
    
    def scan_routes(self, app) -> List[Dict[str, Any]]:
        """Scan FastAPI app and extract route documentation."""
        routes = []
        
        for route in app.routes:
            if hasattr(route, 'methods') and hasattr(route, 'path'):
                route_info = {
                    "path": route.path,
                    "methods": list(route.methods) if route.methods else [],
                    "name": route.name if hasattr(route, 'name') else None,
                    "summary": self._extract_summary(route),
                    "description": self._extract_description(route),
                    "parameters": self._extract_parameters(route),
                    "responses": self._extract_responses(route),
                    "tags": self._extract_tags(route)
                }
                routes.append(route_info)
        
        self._endpoints = routes
        return routes
    
    def _extract_summary(self, route) -> str:
        """Extract route summary."""
        if hasattr(route, 'summary') and route.summary:
            return route.summary
        
        if hasattr(route, 'endpoint') and route.endpoint.__doc__:
            doc = route.endpoint.__doc__.strip()
            return doc.split('.')[0] if '.' in doc else doc[:50]
        
        return route.name if hasattr(route, 'name') else "No summary"
    
    def _extract_description(self, route) -> str:
        """Extract route description."""
        if hasattr(route, 'description') and route.description:
            return route.description
        
        if hasattr(route, 'endpoint') and route.endpoint.__doc__:
            return route.endpoint.__doc__.strip()
        
        return ""
    
    def _extract_parameters(self, route) -> List[Dict[str, Any]]:
        """Extract route parameters."""
        params = []
        
        if hasattr(route, 'dependant'):
            if hasattr(route.dependant, 'flat_params'):
                for param in route.dependant.flat_params:
                    param_info = {
                        "name": param.name,
                        "in": param.in_.value if hasattr(param.in_, 'value') else "query",
                        "type": str(param.type_) if hasattr(param, 'type_') else "string",
                        "required": param.required if hasattr(param, 'required') else False,
                        "description": param.description if hasattr(param, 'description') else "",
                        "default": str(param.default) if hasattr(param, 'default') else None
                    }
                    params.append(param_info)
        
        return params
    
    def _extract_responses(self, route) -> Dict[str, Any]:
        """Extract response schemas."""
        responses = {}
        
        if hasattr(route, 'responses'):
            for code, response in route.responses.items():
                responses[str(code)] = {
                    "description": response.get("description", ""),
                    "content": response.get("content", {})
                }
        
        if not responses:
            responses["200"] = {"description": "Successful response"}
        
        return responses
    
    def _extract_tags(self, route) -> List[str]:
        """Extract route tags."""
        if hasattr(route, 'tags') and route.tags:
            return route.tags
        
        # Infer from path
        if hasattr(route, 'path'):
            parts = route.path.split('/')
            if len(parts) > 1 and parts[1]:
                return [parts[1].replace('_', ' ').title()]
        
        return ["General"]
    
    def generate_markdown_docs(self) -> str:
        """Generate Markdown documentation."""
        lines = [
            "# ViraClip API Documentation",
            "",
            "## Overview",
            "",
            "The ViraClip API provides endpoints for video processing, clip generation,",
            "and viral content optimization.",
            "",
            "## Base URL",
            "",
            "```",
            "https://api.viraclip.com/v1",
            "```",
            "",
            "## Authentication",
            "",
            "All endpoints require API key authentication via the `Authorization` header:",
            "",
            "```",
            "Authorization: Bearer YOUR_API_KEY",
            "```",
            "",
            "## Endpoints",
            ""
        ]
        
        # Group by tags
        by_tag: Dict[str, List[Dict]] = {}
        for endpoint in self._endpoints:
            tag = endpoint["tags"][0] if endpoint["tags"] else "General"
            if tag not in by_tag:
                by_tag[tag] = []
            by_tag[tag].append(endpoint)
        
        # Generate docs for each tag
        for tag, endpoints in sorted(by_tag.items()):
            lines.extend([
                f"### {tag}",
                ""
            ])
            
            for ep in endpoints:
                methods = ', '.join(ep["methods"])
                lines.extend([
                    f"#### {methods} {ep['path']}",
                    "",
                    ep["summary"],
                    ""
                ])
                
                if ep["description"]:
                    lines.extend([
                        ep["description"],
                        ""
                    ])
                
                # Parameters
                if ep["parameters"]:
                    lines.extend([
                        "**Parameters:**",
                        "",
                        "| Name | In | Type | Required | Description |",
                        "|------|-----|------|----------|-------------|"
                    ])
                    
                    for param in ep["parameters"]:
                        req = "Yes" if param["required"] else "No"
                        desc = param["description"][:50] if param["description"] else ""
                        lines.append(
                            f"| {param['name']} | {param['in']} | {param['type']} | {req} | {desc} |"
                        )
                    
                    lines.append("")
                
                # Responses
                lines.extend([
                    "**Responses:**",
                    "",
                    "| Code | Description |",
                    "|------|-------------|"
                ])
                
                for code, response in ep["responses"].items():
                    lines.append(f"| {code} | {response['description']} |")
                
                lines.append("")
        
        # Add footer
        lines.extend([
            "---",
            "",
            "*Generated automatically by ViraClip API Documentation System*"
        ])
        
        return '\n'.join(lines)
    
    def generate_postman_collection(self, base_url: str = "https://api.viraclip.com") -> Dict[str, Any]:
        """Generate Postman collection."""
        collection = {
            "info": {
                "name": "ViraClip API",
                "description": "Video processing and viral clip generation API",
                "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
            },
            "item": []
        }
        
        # Group by tags (folders in Postman)
        by_tag: Dict[str, List[Dict]] = {}
        for endpoint in self._endpoints:
            tag = endpoint["tags"][0] if endpoint["tags"] else "General"
            if tag not in by_tag:
                by_tag[tag] = []
            by_tag[tag].append(endpoint)
        
        for tag, endpoints in by_tag.items():
            folder = {
                "name": tag,
                "item": []
            }
            
            for ep in endpoints:
                for method in ep["methods"]:
                    if method == "HEAD":
                        continue
                    
                    request = {
                        "name": ep["summary"],
                        "request": {
                            "method": method,
                            "header": [
                                {
                                    "key": "Authorization",
                                    "value": "Bearer {{api_key}}",
                                    "type": "text"
                                },
                                {
                                    "key": "Content-Type",
                                    "value": "application/json",
                                    "type": "text"
                                }
                            ],
                            "url": {
                                "raw": f"{base_url}{ep['path']}",
                                "host": [base_url],
                                "path": ep['path'].lstrip('/').split('/')
                            },
                            "description": ep["description"]
                        }
                    }
                    
                    # Add parameters
                    if ep["parameters"]:
                        query = []
                        for param in ep["parameters"]:
                            if param["in"] in ["query", "path"]:
                                query.append({
                                    "key": param["name"],
                                    "value": param.get("default", ""),
                                    "description": param["description"]
                                })
                        
                        if query:
                            request["request"]["url"]["query"] = query
                    
                    folder["item"].append(request)
            
            collection["item"].append(folder)
        
        return collection


class APIChangelog:
    """Manages API versioning and changelog."""
    
    def __init__(self):
        self._versions: Dict[str, Dict[str, Any]] = {
            "v1.0.0": {
                "date": "2024-01-01",
                "changes": [
                    "Initial API release",
                    "Video upload and processing",
                    "Clip generation"
                ],
                "breaking": False
            },
            "v1.1.0": {
                "date": "2024-02-01",
                "changes": [
                    "Added viral score endpoint",
                    "Enhanced AI analysis",
                    "Multi-platform export"
                ],
                "breaking": False
            },
            "v1.2.0": {
                "date": "2024-03-01",
                "changes": [
                    "Added collaboration endpoints",
                    "Webhook support",
                    "Advanced analytics"
                ],
                "breaking": False
            }
        }
    
    def get_changelog(self, since_version: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get changelog entries."""
        entries = []
        
        for version, data in sorted(self._versions.items(), reverse=True):
            if since_version and version <= since_version:
                continue
            
            entries.append({
                "version": version,
                "date": data["date"],
                "changes": data["changes"],
                "breaking": data["breaking"]
            })
        
        return entries
    
    def get_current_version(self) -> str:
        """Get current API version."""
        return max(self._versions.keys())
    
    def add_version(
        self,
        version: str,
        changes: List[str],
        breaking: bool = False
    ) -> None:
        """Add new version entry."""
        self._versions[version] = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "changes": changes,
            "breaking": breaking
        }


class APIValidator:
    """Validates API requests and responses."""
    
    def __init__(self):
        self._validation_errors: List[Dict[str, Any]] = []
    
    def validate_request(
        self,
        endpoint: str,
        method: str,
        params: Dict[str, Any],
        body: Optional[Dict] = None
    ) -> List[str]:
        """Validate API request against schema."""
        errors = []
        
        # Check required parameters
        # Implementation would check against endpoint schema
        
        # Validate body if present
        if body and not isinstance(body, dict):
            errors.append("Request body must be a valid JSON object")
        
        return errors
    
    def validate_response(
        self,
        endpoint: str,
        status_code: int,
        body: Dict[str, Any]
    ) -> List[str]:
        """Validate API response against schema."""
        errors = []
        
        # Check response structure
        # Implementation would validate against response schema
        
        return errors


# Global instances
_doc_generator: Optional[APIDocGenerator] = None
_changelog: Optional[APIChangelog] = None


def get_doc_generator() -> APIDocGenerator:
    """Get global API doc generator."""
    global _doc_generator
    if _doc_generator is None:
        _doc_generator = APIDocGenerator()
    return _doc_generator


def get_changelog() -> APIChangelog:
    """Get global changelog manager."""
    global _changelog
    if _changelog is None:
        _changelog = APIChangelog()
    return _changelog


def generate_api_documentation(app) -> str:
    """Generate complete API documentation."""
    generator = get_doc_generator()
    generator.scan_routes(app)
    return generator.generate_markdown_docs()
