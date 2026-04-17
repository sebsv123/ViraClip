"""
Workflow Automation Service
Visual workflow builder for automated clip processing pipelines.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class WorkflowNodeType(Enum):
    """Types of workflow nodes."""
    TRIGGER = "trigger"
    EXTRACT_VIDEO = "extract_video"
    AI_ANALYZE = "ai_analyze"
    GENERATE_CLIPS = "generate_clips"
    APPLY_EFFECTS = "apply_effects"
    ADD_MUSIC = "add_music"
    EXPORT = "export"
    PUBLISH = "publish"
    CONDITION = "condition"
    DELAY = "delay"
    WEBHOOK = "webhook"
    NOTIFICATION = "notification"


class WorkflowStatus(Enum):
    """Workflow execution status."""
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class WorkflowNode:
    """Single node in workflow."""
    node_id: str
    type: WorkflowNodeType
    name: str
    config: Dict[str, Any]
    position: Dict[str, float]  # x, y for visual editor
    inputs: List[str] = field(default_factory=list)
    outputs: List[str] = field(default_factory=list)


@dataclass
class Workflow:
    """Complete workflow definition."""
    workflow_id: str
    user_id: str
    name: str
    description: str
    status: WorkflowStatus
    nodes: List[WorkflowNode]
    connections: List[Dict[str, str]]  # source -> target
    created_at: str
    updated_at: str
    last_run: Optional[str] = None
    run_count: int = 0


@dataclass
class WorkflowRun:
    """Single workflow execution."""
    run_id: str
    workflow_id: str
    status: str
    started_at: str
    completed_at: Optional[str]
    input_data: Dict[str, Any]
    output_data: Dict[str, Any]
    node_results: Dict[str, Any]
    logs: List[str]


class WorkflowAutomationService:
    """
    Visual workflow automation for video processing.
    """
    
    def __init__(self):
        self._workflows: Dict[str, Workflow] = {}
        self._workflow_runs: Dict[str, WorkflowRun] = {}
        self._templates: Dict[str, Workflow] = {}
        self._initialize_templates()
    
    def _initialize_templates(self):
        """Initialize workflow templates."""
        import uuid
        
        # Viral Shorts Template
        viral_shorts = Workflow(
            workflow_id=f"template_viral_shorts_{uuid.uuid4().hex[:8]}",
            user_id="system",
            name="Viral Shorts Pipeline",
            description="Automatically create viral shorts from long videos",
            status=WorkflowStatus.DRAFT,
            nodes=[
                WorkflowNode(
                    node_id="trigger_1",
                    type=WorkflowNodeType.TRIGGER,
                    name="Video Uploaded",
                    config={"event": "video.uploaded"},
                    position={"x": 100, "y": 100},
                    outputs=["analyze_1"]
                ),
                WorkflowNode(
                    node_id="analyze_1",
                    type=WorkflowNodeType.AI_ANALYZE,
                    name="AI Analysis",
                    config={"model": "virality_v2", "focus": "engagement"},
                    position={"x": 300, "y": 100},
                    inputs=["trigger_1"],
                    outputs=["generate_1"]
                ),
                WorkflowNode(
                    node_id="generate_1",
                    type=WorkflowNodeType.GENERATE_CLIPS,
                    name="Generate Clips",
                    config={"count": 5, "min_duration": 15, "max_duration": 60},
                    position={"x": 500, "y": 100},
                    inputs=["analyze_1"],
                    outputs=["effects_1"]
                ),
                WorkflowNode(
                    node_id="effects_1",
                    type=WorkflowNodeType.APPLY_EFFECTS,
                    name="Apply Effects",
                    config={"effects": ["zoom_pulse", "captions", "thumbnail"]},
                    position={"x": 700, "y": 100},
                    inputs=["generate_1"],
                    outputs=["music_1"]
                ),
                WorkflowNode(
                    node_id="music_1",
                    type=WorkflowNodeType.ADD_MUSIC,
                    name="Add Trending Music",
                    config={"source": "trending", "match_mood": True},
                    position={"x": 900, "y": 100},
                    inputs=["effects_1"],
                    outputs=["export_1"]
                ),
                WorkflowNode(
                    node_id="export_1",
                    type=WorkflowNodeType.EXPORT,
                    name="Export Multi-Platform",
                    config={"platforms": ["youtube", "tiktok", "instagram"], "quality": "1080p"},
                    position={"x": 1100, "y": 100},
                    inputs=["music_1"],
                    outputs=["notify_1"]
                ),
                WorkflowNode(
                    node_id="notify_1",
                    type=WorkflowNodeType.NOTIFICATION,
                    name="Send Notification",
                    config={"channel": "email", "message": "Your viral clips are ready!"},
                    position={"x": 1300, "y": 100},
                    inputs=["export_1"]
                )
            ],
            connections=[
                {"source": "trigger_1", "target": "analyze_1"},
                {"source": "analyze_1", "target": "generate_1"},
                {"source": "generate_1", "target": "effects_1"},
                {"source": "effects_1", "target": "music_1"},
                {"source": "music_1", "target": "export_1"},
                {"source": "export_1", "target": "notify_1"}
            ],
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat()
        )
        
        self._templates["viral_shorts"] = viral_shorts
        
        # Tutorial Content Template
        tutorial = Workflow(
            workflow_id=f"template_tutorial_{uuid.uuid4().hex[:8]}",
            user_id="system",
            name="Tutorial Content Pipeline",
            description="Create educational content with captions and chapters",
            status=WorkflowStatus.DRAFT,
            nodes=[
                WorkflowNode(
                    node_id="trigger_1",
                    type=WorkflowNodeType.TRIGGER,
                    name="Tutorial Uploaded",
                    config={"event": "video.uploaded", "category": "education"},
                    position={"x": 100, "y": 100},
                    outputs=["analyze_1"]
                ),
                WorkflowNode(
                    node_id="analyze_1",
                    type=WorkflowNodeType.AI_ANALYZE,
                    name="Extract Key Moments",
                    config={"focus": "educational_value", "detect_chapters": True},
                    position={"x": 300, "y": 100},
                    inputs=["trigger_1"],
                    outputs=["clips_1"]
                ),
                WorkflowNode(
                    node_id="clips_1",
                    type=WorkflowNodeType.GENERATE_CLIPS,
                    name="Generate Tutorial Clips",
                    config={"style": "tutorial", "add_captions": True, "highlight_code": True},
                    position={"x": 500, "y": 100},
                    inputs=["analyze_1"],
                    outputs=["export_1"]
                ),
                WorkflowNode(
                    node_id="export_1",
                    type=WorkflowNodeType.EXPORT,
                    name="Export with Chapters",
                    config={"include_chapters": True, "platforms": ["youtube"]},
                    position={"x": 700, "y": 100},
                    inputs=["clips_1"]
                )
            ],
            connections=[
                {"source": "trigger_1", "target": "analyze_1"},
                {"source": "analyze_1", "target": "clips_1"},
                {"source": "clips_1", "target": "export_1"}
            ],
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat()
        )
        
        self._templates["tutorial"] = tutorial
    
    async def create_workflow(
        self,
        user_id: str,
        name: str,
        description: str,
        template_id: Optional[str] = None
    ) -> Workflow:
        """Create a new workflow from scratch or template."""
        import uuid
        
        workflow_id = str(uuid.uuid4())
        
        if template_id and template_id in self._templates:
            # Clone from template
            template = self._templates[template_id]
            import copy
            workflow = copy.deepcopy(template)
            workflow.workflow_id = workflow_id
            workflow.user_id = user_id
            workflow.name = name
            workflow.description = description
            workflow.created_at = datetime.now().isoformat()
            workflow.updated_at = datetime.now().isoformat()
        else:
            # Create empty workflow
            workflow = Workflow(
                workflow_id=workflow_id,
                user_id=user_id,
                name=name,
                description=description,
                status=WorkflowStatus.DRAFT,
                nodes=[],
                connections=[],
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat()
            )
        
        self._workflows[workflow_id] = workflow
        logger.info(f"Created workflow {workflow_id} for user {user_id}")
        return workflow
    
    async def add_node(
        self,
        workflow_id: str,
        node_type: WorkflowNodeType,
        name: str,
        config: Dict[str, Any],
        position: Dict[str, float],
        connect_to: Optional[List[str]] = None
    ) -> WorkflowNode:
        """Add a node to workflow."""
        import uuid
        
        if workflow_id not in self._workflows:
            raise ValueError(f"Workflow {workflow_id} not found")
        
        workflow = self._workflows[workflow_id]
        
        node_id = f"node_{uuid.uuid4().hex[:8]}"
        
        node = WorkflowNode(
            node_id=node_id,
            type=node_type,
            name=name,
            config=config,
            position=position,
            outputs=connect_to or []
        )
        
        workflow.nodes.append(node)
        
        # Add connections
        if connect_to:
            for target_id in connect_to:
                workflow.connections.append({"source": node_id, "target": target_id})
        
        workflow.updated_at = datetime.now().isoformat()
        
        return node
    
    async def execute_workflow(
        self,
        workflow_id: str,
        input_data: Dict[str, Any]
    ) -> WorkflowRun:
        """Execute a workflow."""
        import uuid
        
        if workflow_id not in self._workflows:
            raise ValueError(f"Workflow {workflow_id} not found")
        
        workflow = self._workflows[workflow_id]
        
        run_id = str(uuid.uuid4())
        
        run = WorkflowRun(
            run_id=run_id,
            workflow_id=workflow_id,
            status="running",
            started_at=datetime.now().isoformat(),
            completed_at=None,
            input_data=input_data,
            output_data={},
            node_results={},
            logs=[]
        )
        
        self._workflow_runs[run_id] = run
        
        try:
            # Execute nodes in order
            executed_nodes = set()
            node_queue = [n for n in workflow.nodes if n.type == WorkflowNodeType.TRIGGER]
            
            while node_queue:
                node = node_queue.pop(0)
                
                if node.node_id in executed_nodes:
                    continue
                
                # Execute node
                result = await self._execute_node(node, run)
                run.node_results[node.node_id] = result
                executed_nodes.add(node.node_id)
                
                # Find next nodes
                for conn in workflow.connections:
                    if conn["source"] == node.node_id:
                        next_node = next(
                            (n for n in workflow.nodes if n.node_id == conn["target"]),
                            None
                        )
                        if next_node:
                            node_queue.append(next_node)
            
            run.status = "completed"
            run.completed_at = datetime.now().isoformat()
            workflow.run_count += 1
            workflow.last_run = datetime.now().isoformat()
            
        except Exception as e:
            run.status = "failed"
            run.completed_at = datetime.now().isoformat()
            run.logs.append(f"Error: {str(e)}")
            logger.error(f"Workflow {workflow_id} failed: {e}")
        
        return run
    
    async def _execute_node(
        self,
        node: WorkflowNode,
        run: WorkflowRun
    ) -> Dict[str, Any]:
        """Execute a single workflow node."""
        run.logs.append(f"Executing {node.name} ({node.type.value})")
        
        # Simulate execution based on node type
        if node.type == WorkflowNodeType.TRIGGER:
            return {"triggered": True, "input": run.input_data}
        
        elif node.type == WorkflowNodeType.AI_ANALYZE:
            return {"analysis_complete": True, "virality_score": 85}
        
        elif node.type == WorkflowNodeType.GENERATE_CLIPS:
            return {"clips_generated": 5, "duration": 30}
        
        elif node.type == WorkflowNodeType.APPLY_EFFECTS:
            return {"effects_applied": node.config.get("effects", [])}
        
        elif node.type == WorkflowNodeType.EXPORT:
            return {"exported_to": node.config.get("platforms", [])}
        
        elif node.type == WorkflowNodeType.NOTIFICATION:
            return {"notified": True, "channel": node.config.get("channel")}
        
        return {"executed": True}
    
    def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        """Get workflow by ID."""
        return self._workflows.get(workflow_id)
    
    def get_user_workflows(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all workflows for a user."""
        return [
            {
                "workflow_id": w.workflow_id,
                "name": w.name,
                "description": w.description,
                "status": w.status.value,
                "nodes_count": len(w.nodes),
                "run_count": w.run_count,
                "last_run": w.last_run,
                "created_at": w.created_at
            }
            for w in self._workflows.values()
            if w.user_id == user_id
        ]
    
    def get_templates(self) -> List[Dict[str, Any]]:
        """Get available workflow templates."""
        return [
            {
                "template_id": key,
                "name": template.name,
                "description": template.description,
                "nodes_count": len(template.nodes),
                "category": "viral" if "viral" in key else "education" if "tutorial" in key else "general"
            }
            for key, template in self._templates.items()
        ]
    
    async def activate_workflow(self, workflow_id: str) -> bool:
        """Activate workflow for automatic triggers."""
        if workflow_id not in self._workflows:
            return False
        
        self._workflows[workflow_id].status = WorkflowStatus.ACTIVE
        return True
    
    def get_run_status(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Get workflow run status."""
        if run_id not in self._workflow_runs:
            return None
        
        run = self._workflow_runs[run_id]
        return {
            "run_id": run.run_id,
            "workflow_id": run.workflow_id,
            "status": run.status,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
            "logs": run.logs,
            "node_results": run.node_results
        }


# Global instance
_workflow_service: Optional[WorkflowAutomationService] = None


def get_workflow_service() -> WorkflowAutomationService:
    """Get global workflow automation service."""
    global _workflow_service
    if _workflow_service is None:
        _workflow_service = WorkflowAutomationService()
    return _workflow_service
