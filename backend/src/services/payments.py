"""
Payments and Monetization Service
Subscription management, usage-based billing, and payment processing.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)


class PlanType(Enum):
    """Available subscription plans."""
    FREE = "free"
    STARTER = "starter"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class PaymentStatus(Enum):
    """Payment transaction status."""
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"


@dataclass
class SubscriptionPlan:
    """Subscription plan definition."""
    plan_id: str
    name: str
    plan_type: PlanType
    price_monthly: float
    price_yearly: float
    features: List[str]
    limits: Dict[str, int]  # videos_per_month, clips_per_video, etc.
    currency: str = "USD"


@dataclass
class UserSubscription:
    """User subscription state."""
    user_id: str
    plan: SubscriptionPlan
    status: str  # active, cancelled, expired
    started_at: str
    expires_at: str
    payment_method: Optional[str]
    auto_renew: bool
    usage_this_month: Dict[str, int]


@dataclass
class PaymentTransaction:
    """Payment transaction record."""
    transaction_id: str
    user_id: str
    amount: float
    currency: str
    status: PaymentStatus
    payment_method: str
    plan_id: Optional[str]
    created_at: str
    completed_at: Optional[str]
    metadata: Dict[str, Any]


class PaymentService:
    """
    Payment processing and subscription management.
    """
    
    # Plan definitions
    PLANS = {
        PlanType.FREE: SubscriptionPlan(
            plan_id="free",
            name="Free",
            plan_type=PlanType.FREE,
            price_monthly=0.0,
            price_yearly=0.0,
            features=[
                "3 videos per month",
                "Basic clip generation",
                "720p export",
                "Standard templates"
            ],
            limits={
                "videos_per_month": 3,
                "clips_per_video": 5,
                "max_resolution": 720,
                "ai_analysis": 0
            }
        ),
        PlanType.STARTER: SubscriptionPlan(
            plan_id="starter",
            name="Starter",
            plan_type=PlanType.STARTER,
            price_monthly=9.99,
            price_yearly=99.99,
            features=[
                "20 videos per month",
                "Advanced clip generation",
                "1080p export",
                "All templates",
                "Basic analytics"
            ],
            limits={
                "videos_per_month": 20,
                "clips_per_video": 10,
                "max_resolution": 1080,
                "ai_analysis": 50
            }
        ),
        PlanType.PRO: SubscriptionPlan(
            plan_id="pro",
            name="Pro",
            plan_type=PlanType.PRO,
            price_monthly=29.99,
            price_yearly=299.99,
            features=[
                "Unlimited videos",
                "AI-powered clip optimization",
                "4K export",
                "Custom branding",
                "Advanced analytics",
                "Priority processing",
                "API access"
            ],
            limits={
                "videos_per_month": -1,  # Unlimited
                "clips_per_video": 20,
                "max_resolution": 2160,
                "ai_analysis": 500
            }
        ),
        PlanType.ENTERPRISE: SubscriptionPlan(
            plan_id="enterprise",
            name="Enterprise",
            plan_type=PlanType.ENTERPRISE,
            price_monthly=99.99,
            price_yearly=999.99,
            features=[
                "Everything in Pro",
                "White-label solution",
                "Dedicated support",
                "Custom integrations",
                "Team collaboration",
                "SLA guarantee",
                "Advanced security"
            ],
            limits={
                "videos_per_month": -1,
                "clips_per_video": 50,
                "max_resolution": 2160,
                "ai_analysis": -1,  # Unlimited
                "team_members": 10
            }
        )
    }
    
    def __init__(self):
        self._subscriptions: Dict[str, UserSubscription] = {}
        self._transactions: Dict[str, PaymentTransaction] = {}
        self._stripe_api_key: Optional[str] = None
    
    def configure_stripe(self, api_key: str) -> None:
        """Configure Stripe API key."""
        self._stripe_api_key = api_key
        logger.info("Stripe payment processing configured")
    
    async def create_subscription(
        self,
        user_id: str,
        plan_type: PlanType,
        payment_method: str,
        yearly: bool = False
    ) -> UserSubscription:
        """Create new subscription for user."""
        plan = self.PLANS[plan_type]
        
        # Calculate expiration
        if yearly:
            expires = datetime.now() + timedelta(days=365)
        else:
            expires = datetime.now() + timedelta(days=30)
        
        subscription = UserSubscription(
            user_id=user_id,
            plan=plan,
            status="active",
            started_at=datetime.now().isoformat(),
            expires_at=expires.isoformat(),
            payment_method=payment_method,
            auto_renew=True,
            usage_this_month={
                "videos": 0,
                "clips": 0,
                "ai_analysis": 0
            }
        )
        
        self._subscriptions[user_id] = subscription
        
        # Process initial payment
        amount = plan.price_yearly if yearly else plan.price_monthly
        await self._process_payment(user_id, amount, plan.plan_id)
        
        logger.info(f"Created {plan_type.value} subscription for user {user_id}")
        return subscription
    
    async def _process_payment(
        self,
        user_id: str,
        amount: float,
        plan_id: Optional[str] = None
    ) -> PaymentTransaction:
        """Process payment transaction."""
        import uuid
        
        transaction = PaymentTransaction(
            transaction_id=str(uuid.uuid4()),
            user_id=user_id,
            amount=amount,
            currency="USD",
            status=PaymentStatus.PENDING,
            payment_method="stripe",
            plan_id=plan_id,
            created_at=datetime.now().isoformat(),
            completed_at=None,
            metadata={}
        )
        
        self._transactions[transaction.transaction_id] = transaction
        
        # Simulate payment processing
        # In production, this would call Stripe API
        try:
            # Simulate API call
            await asyncio.sleep(0.1)
            
            transaction.status = PaymentStatus.COMPLETED
            transaction.completed_at = datetime.now().isoformat()
            
            logger.info(f"Payment completed: {transaction.transaction_id}")
            
        except Exception as e:
            transaction.status = PaymentStatus.FAILED
            logger.error(f"Payment failed: {e}")
        
        return transaction
    
    def get_subscription(self, user_id: str) -> Optional[UserSubscription]:
        """Get user's current subscription."""
        return self._subscriptions.get(user_id)
    
    def check_feature_access(self, user_id: str, feature: str) -> bool:
        """Check if user has access to a feature."""
        subscription = self._subscriptions.get(user_id)
        
        if not subscription:
            # Default to free plan
            return feature in self.PLANS[PlanType.FREE].features
        
        return feature in subscription.plan.features
    
    def check_usage_limit(
        self,
        user_id: str,
        limit_type: str,
        increment: int = 1
    ) -> Tuple[bool, int, int]:
        """
        Check if user is within usage limits.
        
        Returns:
            (allowed, current_usage, limit)
        """
        subscription = self._subscriptions.get(user_id)
        
        if not subscription:
            # Use free plan limits
            limit = self.PLANS[PlanType.FREE].limits.get(limit_type, 0)
            current = 0
        else:
            limit = subscription.plan.limits.get(limit_type, 0)
            current = subscription.usage_this_month.get(limit_type, 0)
        
        # -1 means unlimited
        if limit == -1:
            return True, current, limit
        
        allowed = (current + increment) <= limit
        
        return allowed, current, limit
    
    def record_usage(self, user_id: str, usage_type: str, amount: int = 1) -> None:
        """Record feature usage for billing."""
        subscription = self._subscriptions.get(user_id)
        
        if subscription:
            if usage_type not in subscription.usage_this_month:
                subscription.usage_this_month[usage_type] = 0
            
            subscription.usage_this_month[usage_type] += amount
    
    async def cancel_subscription(self, user_id: str) -> bool:
        """Cancel user subscription."""
        if user_id not in self._subscriptions:
            return False
        
        subscription = self._subscriptions[user_id]
        subscription.status = "cancelled"
        subscription.auto_renew = False
        
        logger.info(f"Cancelled subscription for user {user_id}")
        return True
    
    async def upgrade_subscription(
        self,
        user_id: str,
        new_plan: PlanType
    ) -> UserSubscription:
        """Upgrade user to new plan."""
        current = self._subscriptions.get(user_id)
        
        if not current:
            raise ValueError("No active subscription")
        
        # Calculate prorated amount
        new_plan_obj = self.PLANS[new_plan]
        
        # Process upgrade payment
        await self._process_payment(user_id, new_plan_obj.price_monthly, new_plan_obj.plan_id)
        
        # Update subscription
        current.plan = new_plan_obj
        current.status = "active"
        
        # Reset expiration
        current.expires_at = (datetime.now() + timedelta(days=30)).isoformat()
        
        logger.info(f"Upgraded user {user_id} to {new_plan.value}")
        return current
    
    def get_available_plans(self) -> List[Dict[str, Any]]:
        """Get list of available subscription plans."""
        return [
            {
                "plan_id": plan.plan_id,
                "name": plan.name,
                "monthly_price": plan.price_monthly,
                "yearly_price": plan.price_yearly,
                "features": plan.features,
                "limits": plan.limits
            }
            for plan in self.PLANS.values()
        ]
    
    def get_usage_report(self, user_id: str) -> Dict[str, Any]:
        """Get usage report for user."""
        subscription = self._subscriptions.get(user_id)
        
        if not subscription:
            return {"error": "No subscription found"}
        
        limits = subscription.plan.limits
        usage = subscription.usage_this_month
        
        return {
            "plan": subscription.plan.name,
            "status": subscription.status,
            "expires_at": subscription.expires_at,
            "usage": {
                key: {
                    "used": usage.get(key, 0),
                    "limit": limit,
                    "remaining": limit - usage.get(key, 0) if limit > 0 else "unlimited",
                    "percentage": (usage.get(key, 0) / limit * 100) if limit > 0 else 0
                }
                for key, limit in limits.items()
            }
        }
    
    async def handle_webhook(
        self,
        provider: str,
        payload: Dict[str, Any]
    ) -> bool:
        """Handle payment provider webhooks."""
        if provider == "stripe":
            event_type = payload.get("type")
            
            if event_type == "invoice.payment_succeeded":
                # Handle successful payment
                customer_id = payload["data"]["object"]["customer"]
                # Update subscription status
                pass
            
            elif event_type == "customer.subscription.deleted":
                # Handle cancellation
                subscription_id = payload["data"]["object"]["id"]
                # Cancel subscription
                pass
        
        return True


# Global instance
_payment_service: Optional[PaymentService] = None


def get_payment_service() -> PaymentService:
    """Get global payment service."""
    global _payment_service
    if _payment_service is None:
        _payment_service = PaymentService()
    return _payment_service


# Convenience functions
def get_user_plan(user_id: str) -> Optional[Dict[str, Any]]:
    """Get user's current plan details."""
    service = get_payment_service()
    subscription = service.get_subscription(user_id)
    
    if not subscription:
        return None
    
    return {
        "plan": subscription.plan.name,
        "status": subscription.status,
        "expires": subscription.expires_at,
        "features": subscription.plan.features
    }


def check_user_limit(user_id: str, limit_type: str) -> Tuple[bool, int, int]:
    """Check if user can use a feature within their limits."""
    return get_payment_service().check_usage_limit(user_id, limit_type)


async def record_feature_usage(user_id: str, feature: str, amount: int = 1) -> None:
    """Record feature usage for billing."""
    get_payment_service().record_usage(user_id, feature, amount)
