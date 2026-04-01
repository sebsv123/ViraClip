"""
Feature Flags System for Gradual Releases
Enables gradual rollout of new features with A/B testing support.
"""

import json
import logging
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass
from enum import Enum
from datetime import datetime

logger = logging.getLogger(__name__)


class RolloutStrategy(Enum):
    """Feature rollout strategies."""
    ALL_USERS = "all_users"           # Enable for everyone
    PERCENTAGE = "percentage"         # Enable for % of users
    USER_LIST = "user_list"           # Enable for specific users
    GRADUAL = "gradual"               # Gradually increase %
    CANARY = "canary"                 # Enable for small group first


@dataclass
class FeatureFlag:
    """Feature flag configuration."""
    name: str
    enabled: bool
    strategy: RolloutStrategy
    rollout_percentage: int  # 0-100
    allowed_users: List[str]
    blocked_users: List[str]
    metadata: Dict[str, Any]
    created_at: str
    updated_at: str


class FeatureFlagManager:
    """
    Manages feature flags with multiple rollout strategies.
    """
    
    def __init__(self, storage_path: Optional[str] = None):
        self.flags: Dict[str, FeatureFlag] = {}
        self._user_callbacks: Dict[str, Callable] = {}
        self._storage_path = storage_path or "/app/data/feature_flags.json"
        self._load_flags()
    
    def _load_flags(self) -> None:
        """Load flags from storage."""
        try:
            import os
            if os.path.exists(self._storage_path):
                with open(self._storage_path, 'r') as f:
                    data = json.load(f)
                    for name, flag_data in data.items():
                        self.flags[name] = FeatureFlag(**flag_data)
        except Exception as e:
            logger.warning(f"Failed to load feature flags: {e}")
    
    def _save_flags(self) -> None:
        """Save flags to storage."""
        try:
            data = {
                name: {
                    "name": flag.name,
                    "enabled": flag.enabled,
                    "strategy": flag.strategy.value,
                    "rollout_percentage": flag.rollout_percentage,
                    "allowed_users": flag.allowed_users,
                    "blocked_users": flag.blocked_users,
                    "metadata": flag.metadata,
                    "created_at": flag.created_at,
                    "updated_at": flag.updated_at
                }
                for name, flag in self.flags.items()
            }
            
            import os
            os.makedirs(os.path.dirname(self._storage_path), exist_ok=True)
            with open(self._storage_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save feature flags: {e}")
    
    def create_flag(
        self,
        name: str,
        enabled: bool = False,
        strategy: RolloutStrategy = RolloutStrategy.ALL_USERS,
        rollout_percentage: int = 0,
        allowed_users: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> FeatureFlag:
        """Create a new feature flag."""
        now = datetime.now().isoformat()
        
        flag = FeatureFlag(
            name=name,
            enabled=enabled,
            strategy=strategy,
            rollout_percentage=rollout_percentage,
            allowed_users=allowed_users or [],
            blocked_users=[],
            metadata=metadata or {},
            created_at=now,
            updated_at=now
        )
        
        self.flags[name] = flag
        self._save_flags()
        
        logger.info(f"Created feature flag: {name} ({strategy.value})")
        return flag
    
    def is_enabled(
        self,
        flag_name: str,
        user_id: Optional[str] = None,
        user_attributes: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Check if a feature is enabled for a user.
        
        Args:
            flag_name: Name of the feature flag
            user_id: User identifier
            user_attributes: Additional user attributes for targeting
        """
        if flag_name not in self.flags:
            return False
        
        flag = self.flags[flag_name]
        
        # Check if globally disabled
        if not flag.enabled:
            return False
        
        # Check blocked users
        if user_id and user_id in flag.blocked_users:
            return False
        
        # Apply rollout strategy
        if flag.strategy == RolloutStrategy.ALL_USERS:
            return True
        
        elif flag.strategy == RolloutStrategy.USER_LIST:
            return user_id in flag.allowed_users if user_id else False
        
        elif flag.strategy == RolloutStrategy.PERCENTAGE:
            if not user_id:
                return False
            # Deterministic hashing for consistent experience
            import hashlib
            hash_val = int(hashlib.md5(f"{user_id}:{flag_name}".encode()).hexdigest(), 16)
            user_percentage = hash_val % 100
            return user_percentage < flag.rollout_percentage
        
        elif flag.strategy == RolloutStrategy.GRADUAL:
            # Gradual rollout with time-based increase
            days_since_creation = (
                datetime.now() - datetime.fromisoformat(flag.created_at)
            ).days
            
            # Increase 10% per day
            effective_percentage = min(100, days_since_creation * 10)
            
            if not user_id:
                return False
            
            import hashlib
            hash_val = int(hashlib.md5(f"{user_id}:{flag_name}".encode()).hexdigest(), 16)
            user_percentage = hash_val % 100
            return user_percentage < effective_percentage
        
        elif flag.strategy == RolloutStrategy.CANARY:
            # Canary - only allowed users + small random group
            if user_id in flag.allowed_users:
                return True
            
            # Additional 5% random users
            if not user_id:
                return False
            
            import hashlib
            hash_val = int(hashlib.md5(f"{user_id}:{flag_name}".encode()).hexdigest(), 16)
            return (hash_val % 100) < 5
        
        return False
    
    def enable_for_user(self, flag_name: str, user_id: str) -> bool:
        """Enable a feature flag for a specific user."""
        if flag_name not in self.flags:
            return False
        
        flag = self.flags[flag_name]
        
        if user_id not in flag.allowed_users:
            flag.allowed_users.append(user_id)
            flag.updated_at = datetime.now().isoformat()
            self._save_flags()
        
        return True
    
    def disable_for_user(self, flag_name: str, user_id: str) -> bool:
        """Disable a feature flag for a specific user."""
        if flag_name not in self.flags:
            return False
        
        flag = self.flags[flag_name]
        
        if user_id not in flag.blocked_users:
            flag.blocked_users.append(user_id)
            flag.updated_at = datetime.now().isoformat()
            self._save_flags()
        
        return True
    
    def update_rollout(
        self,
        flag_name: str,
        percentage: int
    ) -> bool:
        """Update rollout percentage for a flag."""
        if flag_name not in self.flags:
            return False
        
        flag = self.flags[flag_name]
        flag.rollout_percentage = max(0, min(100, percentage))
        flag.updated_at = datetime.now().isoformat()
        self._save_flags()
        
        logger.info(f"Updated {flag_name} rollout to {flag.rollout_percentage}%")
        return True
    
    def toggle_flag(self, flag_name: str) -> bool:
        """Toggle a feature flag on/off."""
        if flag_name not in self.flags:
            return False
        
        flag = self.flags[flag_name]
        flag.enabled = not flag.enabled
        flag.updated_at = datetime.now().isoformat()
        self._save_flags()
        
        logger.info(f"Toggled {flag_name} to {flag.enabled}")
        return True
    
    def get_flag_status(self, flag_name: str) -> Optional[Dict[str, Any]]:
        """Get detailed status of a feature flag."""
        if flag_name not in self.flags:
            return None
        
        flag = self.flags[flag_name]
        
        return {
            "name": flag.name,
            "enabled": flag.enabled,
            "strategy": flag.strategy.value,
            "rollout_percentage": flag.rollout_percentage,
            "allowed_users_count": len(flag.allowed_users),
            "blocked_users_count": len(flag.blocked_users),
            "metadata": flag.metadata,
            "created_at": flag.created_at,
            "updated_at": flag.updated_at
        }
    
    def get_all_flags(self) -> Dict[str, Dict[str, Any]]:
        """Get all feature flags."""
        return {
            name: self.get_flag_status(name)
            for name in self.flags.keys()
        }
    
    def delete_flag(self, flag_name: str) -> bool:
        """Delete a feature flag."""
        if flag_name in self.flags:
            del self.flags[flag_name]
            self._save_flags()
            return True
        return False
    
    def register_user_callback(
        self,
        flag_name: str,
        callback: Callable[[str, bool], None]
    ) -> None:
        """Register callback for when flag changes for a user."""
        self._user_callbacks[flag_name] = callback


class FeatureFlagMiddleware:
    """FastAPI middleware to inject feature flags into requests."""
    
    def __init__(self, flag_manager: FeatureFlagManager):
        self.flag_manager = flag_manager
    
    async def __call__(self, request, call_next):
        """Process request and inject enabled features."""
        # Get user ID from request (customize based on your auth)
        user_id = getattr(request.state, "user_id", None)
        
        # Check all flags for this user
        enabled_features = []
        for flag_name in self.flag_manager.flags.keys():
            if self.flag_manager.is_enabled(flag_name, user_id):
                enabled_features.append(flag_name)
        
        # Inject into request state
        request.state.enabled_features = enabled_features
        request.state.feature_flags = self.flag_manager
        
        response = await call_next(request)
        
        # Add feature headers (optional)
        response.headers["X-Enabled-Features"] = ",".join(enabled_features)
        
        return response


# Global instance
_flag_manager: Optional[FeatureFlagManager] = None


def get_feature_flag_manager() -> FeatureFlagManager:
    """Get global feature flag manager instance."""
    global _flag_manager
    if _flag_manager is None:
        _flag_manager = FeatureFlagManager()
    return _flag_manager


def is_feature_enabled(
    flag_name: str,
    user_id: Optional[str] = None
) -> bool:
    """Convenience function to check if feature is enabled."""
    return get_feature_flag_manager().is_enabled(flag_name, user_id)


# Common feature flags for the platform
DEFAULT_FLAGS = {
    "smart_auto_editing": {
        "strategy": RolloutStrategy.GRADUAL,
        "enabled": True,
        "description": "AI-powered auto editing with viral rules"
    },
    "ab_testing_virality": {
        "strategy": RolloutStrategy.PERCENTAGE,
        "enabled": True,
        "rollout_percentage": 50,
        "description": "A/B testing for virality algorithms"
    },
    "enhanced_broll": {
        "strategy": RolloutStrategy.ALL_USERS,
        "enabled": True,
        "description": "Visual context-aware B-roll suggestions"
    },
    "collaboration_beta": {
        "strategy": RolloutStrategy.USER_LIST,
        "enabled": True,
        "allowed_users": [],  # Add beta users here
        "description": "Multi-user collaboration features"
    },
    "advanced_analytics": {
        "strategy": RolloutStrategy.CANARY,
        "enabled": True,
        "description": "Advanced analytics and reporting"
    }
}


def initialize_default_flags() -> None:
    """Initialize default feature flags."""
    manager = get_feature_flag_manager()
    
    for flag_name, config in DEFAULT_FLAGS.items():
        if flag_name not in manager.flags:
            manager.create_flag(
                name=flag_name,
                enabled=config.get("enabled", False),
                strategy=config.get("strategy", RolloutStrategy.ALL_USERS),
                rollout_percentage=config.get("rollout_percentage", 0),
                allowed_users=config.get("allowed_users", []),
                metadata={"description": config.get("description", "")}
            )
