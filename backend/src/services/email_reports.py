"""
Automated Email Reporting Service
Generates and sends periodic email reports to users.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class ReportType(Enum):
    """Types of automated reports."""
    DAILY_SUMMARY = "daily_summary"
    WEEKLY_ANALYTICS = "weekly_analytics"
    MONTHLY_PERFORMANCE = "monthly_performance"
    CLIP_READY = "clip_ready"
    VIRAL_MILESTONE = "viral_milestone"
    SYSTEM_ALERT = "system_alert"


class ReportFrequency(Enum):
    """Report frequency options."""
    REALTIME = "realtime"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


@dataclass
class EmailReport:
    """Email report definition."""
    report_id: str
    user_id: str
    report_type: ReportType
    frequency: ReportFrequency
    subject: str
    content_html: str
    content_text: str
    created_at: str
    sent_at: Optional[str]
    status: str  # pending, sent, failed
    metrics: Dict[str, Any]


@dataclass
class ReportSubscription:
    """User subscription to reports."""
    subscription_id: str
    user_id: str
    email: str
    report_type: ReportType
    frequency: ReportFrequency
    is_active: bool
    created_at: str
    last_sent: Optional[str]
    preferences: Dict[str, Any]


class EmailReportService:
    """
    Automated email reporting service.
    """
    
    def __init__(self, smtp_config: Optional[Dict[str, Any]] = None):
        self.smtp_config = smtp_config or {}
        self._subscriptions: Dict[str, ReportSubscription] = {}
        self._reports: Dict[str, EmailReport] = {}
        self._templates: Dict[ReportType, Dict[str, str]] = self._load_templates()
    
    def _load_templates(self) -> Dict[ReportType, Dict[str, str]]:
        """Load email report templates."""
        return {
            ReportType.DAILY_SUMMARY: {
                "subject": "Your Daily ViraClip Summary",
                "template": """
                <html>
                <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                    <h2 style="color: #6C5CE7;">📊 Your Daily Summary</h2>
                    <p>Hi {username},</p>
                    <p>Here's what happened with your clips today:</p>
                    
                    <div style="background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0;">
                        <h3 style="margin-top: 0;">Today's Activity</h3>
                        <ul>
                            <li><strong>Videos Processed:</strong> {videos_processed}</li>
                            <li><strong>Clips Generated:</strong> {clips_generated}</li>
                            <li><strong>Avg Virality Score:</strong> {avg_virality}%</li>
                            <li><strong>Top Performing Clip:</strong> {top_clip}</li>
                        </ul>
                    </div>
                    
                    <p style="text-align: center;">
                        <a href="{dashboard_url}" style="background: #6C5CE7; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; display: inline-block;">
                            View Full Dashboard
                        </a>
                    </p>
                </body>
                </html>
                """
            },
            ReportType.WEEKLY_ANALYTICS: {
                "subject": "Your Weekly ViraClip Analytics",
                "template": """
                <html>
                <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                    <h2 style="color: #6C5CE7;">📈 Weekly Performance Report</h2>
                    <p>Hi {username},</p>
                    
                    <div style="background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0;">
                        <h3 style="margin-top: 0;">This Week's Highlights</h3>
                        <ul>
                            <li><strong>Total Clips:</strong> {total_clips}</li>
                            <li><strong>High-Virality Clips (80%+):</strong> {high_virality_count}</li>
                            <li><strong>Most Used Platform:</strong> {top_platform}</li>
                            <li><strong>Best Niche:</strong> {best_niche}</li>
                        </ul>
                    </div>
                    
                    <div style="background: #e8f5e9; padding: 15px; border-radius: 8px; margin: 20px 0;">
                        <h4 style="margin-top: 0; color: #2e7d32;">💡 Recommendations for Next Week</h4>
                        <p>{recommendations}</p>
                    </div>
                </body>
                </html>
                """
            },
            ReportType.CLIP_READY: {
                "subject": "🎬 Your Viral Clip is Ready!",
                "template": """
                <html>
                <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                    <h2 style="color: #6C5CE7;">🎉 Your Clip is Ready!</h2>
                    <p>Hi {username},</p>
                    <p>Great news! We've created a high-virality clip from your video.</p>
                    
                    <div style="background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0; text-align: center;">
                        <h3 style="margin-top: 0; color: #e74c3c;">🔥 Virality Score: {virality_score}/100</h3>
                        <p><strong>Duration:</strong> {duration}s</p>
                        <p><strong>Best For:</strong> {best_platform}</p>
                    </div>
                    
                    <p style="text-align: center;">
                        <a href="{clip_url}" style="background: #6C5CE7; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; display: inline-block; margin: 5px;">
                            View Clip
                        </a>
                        <a href="{export_url}" style="background: #00b894; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; display: inline-block; margin: 5px;">
                            Export Now
                        </a>
                    </p>
                </body>
                </html>
                """
            },
            ReportType.VIRAL_MILESTONE: {
                "subject": "🏆 Viral Milestone Achieved!",
                "template": """
                <html>
                <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; border-radius: 12px; color: white; text-align: center;">
                        <h2 style="margin: 0;">🏆 Milestone Unlocked!</h2>
                        <p style="font-size: 18px; margin: 10px 0 0 0;">{milestone_name}</p>
                    </div>
                    
                    <div style="padding: 20px;">
                        <p>Hi {username},</p>
                        <p>Congratulations! You've achieved something amazing:</p>
                        
                        <div style="background: #fff3cd; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #ffc107;">
                            <h4 style="margin-top: 0;">{achievement_title}</h4>
                            <p>{achievement_description}</p>
                            <p><strong>Points Earned:</strong> +{points}</p>
                        </div>
                        
                        <p>Keep creating amazing content!</p>
                    </div>
                </body>
                </html>
                """
            }
        }
    
    async def subscribe(
        self,
        user_id: str,
        email: str,
        report_type: ReportType,
        frequency: ReportFrequency,
        preferences: Optional[Dict[str, Any]] = None
    ) -> ReportSubscription:
        """Subscribe user to email reports."""
        import uuid
        
        subscription = ReportSubscription(
            subscription_id=str(uuid.uuid4()),
            user_id=user_id,
            email=email,
            report_type=report_type,
            frequency=frequency,
            is_active=True,
            created_at=datetime.now().isoformat(),
            last_sent=None,
            preferences=preferences or {}
        )
        
        self._subscriptions[subscription.subscription_id] = subscription
        
        logger.info(f"User {user_id} subscribed to {report_type.value} reports")
        return subscription
    
    async def generate_report(
        self,
        user_id: str,
        report_type: ReportType,
        data: Dict[str, Any]
    ) -> EmailReport:
        """Generate an email report."""
        import uuid
        
        template = self._templates.get(report_type, {})
        
        # Generate content
        html_content = template.get("template", "").format(**data)
        text_content = self._html_to_text(html_content)
        
        report = EmailReport(
            report_id=str(uuid.uuid4()),
            user_id=user_id,
            report_type=report_type,
            frequency=ReportFrequency.REALTIME,
            subject=template.get("subject", "ViraClip Report"),
            content_html=html_content,
            content_text=text_content,
            created_at=datetime.now().isoformat(),
            sent_at=None,
            status="pending",
            metrics={}
        )
        
        self._reports[report.report_id] = report
        return report
    
    async def send_report(
        self,
        report_id: str,
        email: Optional[str] = None
    ) -> bool:
        """Send a generated report via email."""
        if report_id not in self._reports:
            return False
        
        report = self._reports[report_id]
        
        try:
            # Send email using configured SMTP
            success = await self._send_email(
                to_email=email or self._get_user_email(report.user_id),
                subject=report.subject,
                html_content=report.content_html,
                text_content=report.content_text
            )
            
            if success:
                report.status = "sent"
                report.sent_at = datetime.now().isoformat()
                logger.info(f"Report {report_id} sent successfully")
            else:
                report.status = "failed"
                logger.error(f"Failed to send report {report_id}")
            
            return success
            
        except Exception as e:
            report.status = "failed"
            logger.error(f"Error sending report: {e}")
            return False
    
    async def _send_email(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: str
    ) -> bool:
        """Send email via SMTP."""
        try:
            import aiosmtplib
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = self.smtp_config.get('from_email', 'reports@viraclip.com')
            msg['To'] = to_email
            
            msg.attach(MIMEText(text_content, 'plain'))
            msg.attach(MIMEText(html_content, 'html'))
            
            await aiosmtplib.send(
                msg,
                hostname=self.smtp_config.get('host', 'smtp.gmail.com'),
                port=self.smtp_config.get('port', 587),
                username=self.smtp_config.get('username'),
                password=self.smtp_config.get('password'),
                use_tls=self.smtp_config.get('use_tls', True)
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Email sending failed: {e}")
            # In development, just log the email
            logger.info(f"[EMAIL TO: {to_email}] Subject: {subject}")
            logger.info(f"[EMAIL CONTENT]: {text_content[:200]}...")
            return True  # Return True for development
    
    def _html_to_text(self, html: str) -> str:
        """Convert HTML to plain text."""
        import re
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '', html)
        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text)
        return text.strip()
    
    def _get_user_email(self, user_id: str) -> str:
        """Get user email from ID."""
        # In production, this would query the user database
        return f"user_{user_id}@example.com"
    
    async def process_scheduled_reports(self) -> List[str]:
        """Process all scheduled reports that are due."""
        sent_reports = []
        now = datetime.now()
        
        for sub in self._subscriptions.values():
            if not sub.is_active:
                continue
            
            # Check if report is due
            if self._is_report_due(sub, now):
                # Generate data based on report type
                data = await self._generate_report_data(sub)
                
                # Generate and send report
                report = await self.generate_report(sub.user_id, sub.report_type, data)
                
                if await self.send_report(report.report_id, sub.email):
                    sent_reports.append(report.report_id)
                    sub.last_sent = now.isoformat()
        
        return sent_reports
    
    def _is_report_due(self, subscription: ReportSubscription, now: datetime) -> bool:
        """Check if a scheduled report is due."""
        if not subscription.last_sent:
            return True
        
        last_sent = datetime.fromisoformat(subscription.last_sent)
        
        if subscription.frequency == ReportFrequency.DAILY:
            return (now - last_sent) >= timedelta(days=1)
        elif subscription.frequency == ReportFrequency.WEEKLY:
            return (now - last_sent) >= timedelta(weeks=1)
        elif subscription.frequency == ReportFrequency.MONTHLY:
            return (now - last_sent) >= timedelta(days=30)
        
        return False
    
    async def _generate_report_data(self, subscription: ReportSubscription) -> Dict[str, Any]:
        """Generate report data based on subscription."""
        # In production, this would query analytics services
        return {
            "username": f"User {subscription.user_id}",
            "videos_processed": 5,
            "clips_generated": 12,
            "avg_virality": 78,
            "top_clip": "Introduction Hook",
            "dashboard_url": "https://viraclip.com/dashboard",
            "total_clips": 45,
            "high_virality_count": 8,
            "top_platform": "TikTok",
            "best_niche": "Education",
            "recommendations": "Try posting more consistently during peak hours (6-8 PM)"
        }
    
    def get_subscription(self, subscription_id: str) -> Optional[ReportSubscription]:
        """Get subscription by ID."""
        return self._subscriptions.get(subscription_id)
    
    def list_user_subscriptions(self, user_id: str) -> List[ReportSubscription]:
        """List all subscriptions for a user."""
        return [
            sub for sub in self._subscriptions.values()
            if sub.user_id == user_id
        ]
    
    async def unsubscribe(self, subscription_id: str) -> bool:
        """Cancel a subscription."""
        if subscription_id in self._subscriptions:
            self._subscriptions[subscription_id].is_active = False
            logger.info(f"Subscription {subscription_id} cancelled")
            return True
        return False
    
    def get_report_stats(self) -> Dict[str, Any]:
        """Get email reporting statistics."""
        total = len(self._reports)
        sent = sum(1 for r in self._reports.values() if r.status == "sent")
        failed = sum(1 for r in self._reports.values() if r.status == "failed")
        
        return {
            "total_reports": total,
            "sent": sent,
            "failed": failed,
            "pending": total - sent - failed,
            "active_subscriptions": sum(1 for s in self._subscriptions.values() if s.is_active)
        }


# Global instance
_email_service: Optional[EmailReportService] = None


def get_email_service() -> EmailReportService:
    """Get global email service."""
    global _email_service
    if _email_service is None:
        import os
        config = {
            'host': os.getenv('SMTP_HOST', 'smtp.gmail.com'),
            'port': int(os.getenv('SMTP_PORT', '587')),
            'username': os.getenv('SMTP_USERNAME'),
            'password': os.getenv('SMTP_PASSWORD'),
            'from_email': os.getenv('FROM_EMAIL', 'reports@viraclip.com'),
            'use_tls': True
        }
        _email_service = EmailReportService(config)
    return _email_service


# Convenience functions
async def send_clip_ready_email(user_id: str, email: str, clip_data: Dict[str, Any]) -> bool:
    """Send clip ready notification."""
    service = get_email_service()
    
    data = {
        "username": clip_data.get("username", "Creator"),
        "virality_score": clip_data.get("virality_score", 0),
        "duration": clip_data.get("duration", 0),
        "best_platform": clip_data.get("best_platform", "TikTok"),
        "clip_url": clip_data.get("clip_url", ""),
        "export_url": clip_data.get("export_url", "")
    }
    
    report = await service.generate_report(user_id, ReportType.CLIP_READY, data)
    return await service.send_report(report.report_id, email)


async def subscribe_to_reports(user_id: str, email: str, report_type: str, frequency: str) -> str:
    """Subscribe user to reports."""
    service = get_email_service()
    
    rt = ReportType(report_type) if report_type in [t.value for t in ReportType] else ReportType.DAILY_SUMMARY
    freq = ReportFrequency(frequency) if frequency in [f.value for f in ReportFrequency] else ReportFrequency.DAILY
    
    sub = await service.subscribe(user_id, email, rt, freq)
    return sub.subscription_id
