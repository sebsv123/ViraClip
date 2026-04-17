"""
PDF Report Generation Service
Automated PDF report generation for analytics and insights.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class ReportType(Enum):
    """Types of PDF reports."""
    PERFORMANCE = "performance"
    ANALYTICS = "analytics"
    VIRALITY = "virality"
    ENGAGEMENT = "engagement"
    COMPARISON = "comparison"
    AUDIT = "audit"


class ReportTemplate(Enum):
    """Report templates."""
    DAILY_SUMMARY = "daily_summary"
    WEEKLY_ANALYTICS = "weekly_analytics"
    MONTHLY_PERFORMANCE = "monthly_performance"
    CAMPAIGN_REPORT = "campaign_report"
    AUDIT_TRAIL = "audit_trail"


@dataclass
class PDFReport:
    """Generated PDF report."""
    report_id: str
    user_id: str
    report_type: ReportType
    template: ReportTemplate
    title: str
    generated_at: str
    file_path: Path
    file_size_bytes: int
    page_count: int
    data_summary: Dict[str, Any]


class PDFReportService:
    """
    Automated PDF report generation service.
    """
    
    def __init__(self, output_dir: Path = Path("/app/reports")):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._reports: Dict[str, PDFReport] = {}
        self._templates: Dict[str, Dict[str, Any]] = {}
        self._initialize_templates()
    
    def _initialize_templates(self):
        """Initialize report templates."""
        self._templates = {
            "daily_summary": {
                "title": "Daily Performance Summary",
                "sections": ["overview", "metrics", "top_performers", "recommendations"],
                "page_count": 3
            },
            "weekly_analytics": {
                "title": "Weekly Analytics Report",
                "sections": ["executive_summary", "engagement", "growth", "comparison"],
                "page_count": 8
            },
            "monthly_performance": {
                "title": "Monthly Performance Report",
                "sections": ["overview", "detailed_metrics", "trends", "goals", "forecast"],
                "page_count": 15
            },
            "campaign_report": {
                "title": "Campaign Performance Report",
                "sections": ["campaign_overview", "results", "audience", "roi", "insights"],
                "page_count": 12
            }
        }
    
    async def generate_report(
        self,
        user_id: str,
        report_type: ReportType,
        template: ReportTemplate,
        title: str,
        data: Dict[str, Any],
        date_range: tuple,
        branding: Optional[Dict[str, str]] = None
    ) -> PDFReport:
        """
        Generate PDF report from data.
        
        Args:
            user_id: User identifier
            report_type: Type of report
            template: Report template
            title: Report title
            data: Report data
            date_range: (start_date, end_date)
            branding: Optional branding config
        """
        import uuid
        
        report_id = f"report_{uuid.uuid4().hex[:12]}"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{report_id}_{template.value}.pdf"
        file_path = self.output_dir / filename
        
        # Build PDF content
        pdf_content = await self._build_pdf_content(
            template, title, data, date_range, branding
        )
        
        # Write PDF (simulated)
        await self._write_pdf(file_path, pdf_content)
        
        # Get file size
        file_size = file_path.stat().st_size if file_path.exists() else 0
        
        report = PDFReport(
            report_id=report_id,
            user_id=user_id,
            report_type=report_type,
            template=template,
            title=title,
            generated_at=datetime.now().isoformat(),
            file_path=file_path,
            file_size_bytes=file_size,
            page_count=self._templates.get(template.value, {}).get("page_count", 5),
            data_summary={
                "date_range": date_range,
                "data_points": len(data),
                "key_metrics": list(data.keys())[:5]
            }
        )
        
        self._reports[report_id] = report
        
        logger.info(f"Generated PDF report {report_id}: {title} ({file_size} bytes)")
        return report
    
    async def _build_pdf_content(
        self,
        template: ReportTemplate,
        title: str,
        data: Dict[str, Any],
        date_range: tuple,
        branding: Optional[Dict[str, str]]
    ) -> str:
        """Build PDF content (HTML-based for conversion)."""
        template_config = self._templates.get(template.value, {})
        sections = template_config.get("sections", ["content"])
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>{title}</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; }}
                .header {{ text-align: center; margin-bottom: 30px; }}
                .title {{ font-size: 24px; font-weight: bold; color: #333; }}
                .subtitle {{ font-size: 14px; color: #666; margin-top: 10px; }}
                .section {{ margin: 20px 0; page-break-inside: avoid; }}
                .section-title {{ font-size: 18px; font-weight: bold; color: #444; 
                                border-bottom: 2px solid #007bff; padding-bottom: 5px; }}
                .metric {{ display: inline-block; margin: 10px; padding: 15px; 
                         background: #f8f9fa; border-radius: 5px; min-width: 150px; }}
                .metric-value {{ font-size: 24px; font-weight: bold; color: #007bff; }}
                .metric-label {{ font-size: 12px; color: #666; }}
                table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
                th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }}
                th {{ background: #f8f9fa; font-weight: bold; }}
                .footer {{ text-align: center; margin-top: 30px; font-size: 10px; color: #999; }}
            </style>
        </head>
        <body>
            <div class="header">
                <div class="title">{title}</div>
                <div class="subtitle">Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}</div>
                <div class="subtitle">Period: {date_range[0]} to {date_range[1]}</div>
                {f'<div class="subtitle">{branding.get("company_name", "")}</div>' if branding else ''}
            </div>
        """
        
        # Add sections
        for section in sections:
            html_content += await self._build_section(section, data)
        
        html_content += """
            <div class="footer">
                Generated by ViraClip Analytics Engine
            </div>
        </body>
        </html>
        """
        
        return html_content
    
    async def _build_section(self, section: str, data: Dict[str, Any]) -> str:
        """Build a report section."""
        if section == "overview":
            return self._build_overview_section(data)
        elif section == "metrics":
            return self._build_metrics_section(data)
        elif section == "top_performers":
            return self._build_top_performers_section(data)
        elif section == "engagement":
            return self._build_engagement_section(data)
        elif section == "recommendations":
            return self._build_recommendations_section(data)
        else:
            return f'<div class="section"><div class="section-title">{section.replace("_", " ").title()}</div></div>'
    
    def _build_overview_section(self, data: Dict[str, Any]) -> str:
        """Build overview section."""
        return """
        <div class="section">
            <div class="section-title">Executive Overview</div>
            <div style="margin: 15px 0; line-height: 1.6;">
                <p>This report provides a comprehensive analysis of your content performance.
                Key highlights include strong engagement rates and growing audience reach.</p>
            </div>
        </div>
        """
    
    def _build_metrics_section(self, data: Dict[str, Any]) -> str:
        """Build key metrics section."""
        metrics_html = '<div class="section"><div class="section-title">Key Metrics</div><div>'
        
        # Sample metrics
        metrics = [
            ("Total Views", "125,432", "+15%"),
            ("Engagement Rate", "8.5%", "+2.3%"),
            ("Clips Generated", "47", "+12"),
            ("Avg Virality Score", "72.5", "+5.2")
        ]
        
        for label, value, change in metrics:
            metrics_html += f"""
            <div class="metric">
                <div class="metric-value">{value}</div>
                <div class="metric-label">{label}</div>
                <div style="font-size: 11px; color: #28a745;">{change}</div>
            </div>
            """
        
        metrics_html += '</div></div>'
        return metrics_html
    
    def _build_top_performers_section(self, data: Dict[str, Any]) -> str:
        """Build top performers section."""
        return """
        <div class="section">
            <div class="section-title">Top Performing Content</div>
            <table>
                <tr>
                    <th>Content</th>
                    <th>Views</th>
                    <th>Engagement</th>
                    <th>Virality Score</th>
                </tr>
                <tr>
                    <td>Tutorial: AI Basics</td>
                    <td>45,231</td>
                    <td>12.5%</td>
                    <td>88.5</td>
                </tr>
                <tr>
                    <td>Quick Tips #15</td>
                    <td>32,109</td>
                    <td>9.8%</td>
                    <td>76.2</td>
                </tr>
            </table>
        </div>
        """
    
    def _build_engagement_section(self, data: Dict[str, Any]) -> str:
        """Build engagement analysis section."""
        return """
        <div class="section">
            <div class="section-title">Engagement Analysis</div>
            <p>Your content is performing well across all platforms with a strong engagement rate of 8.5%.</p>
            <ul>
                <li>YouTube: Highest watch time (4:32 avg)</li>
                <li>TikTok: Best virality coefficient (1.8x)</li>
                <li>Instagram: Strong story engagement (15%)</li>
            </ul>
        </div>
        """
    
    def _build_recommendations_section(self, data: Dict[str, Any]) -> str:
        """Build recommendations section."""
        return """
        <div class="section">
            <div class="section-title">Recommendations</div>
            <ol>
                <li>Increase posting frequency during peak hours (12PM, 7PM)</li>
                <li>Focus on tutorial content - 40% higher engagement</li>
                <li>Optimize thumbnails for mobile viewing</li>
                <li>Cross-post to emerging platforms for growth</li>
            </ol>
        </div>
        """
    
    async def _write_pdf(self, file_path: Path, content: str):
        """Write PDF to file (simulated)."""
        # In production, use libraries like WeasyPrint, pdfkit, or ReportLab
        # For now, write HTML as placeholder
        with open(file_path.with_suffix(".html"), "w") as f:
            f.write(content)
        
        # Simulate PDF creation
        with open(file_path, "wb") as f:
            f.write(b"%PDF-1.4 simulated")
    
    async def schedule_report(
        self,
        user_id: str,
        report_type: ReportType,
        template: ReportTemplate,
        schedule: str,  # cron expression
        email_recipients: List[str]
    ) -> str:
        """Schedule automated report generation."""
        import uuid
        
        schedule_id = str(uuid.uuid4())
        
        logger.info(
            f"Scheduled {report_type.value} report ({template.value}) "
            f"for user {user_id}: {schedule}"
        )
        
        return schedule_id
    
    def get_user_reports(
        self,
        user_id: str,
        report_type: Optional[ReportType] = None
    ) -> List[Dict[str, Any]]:
        """Get user's generated reports."""
        reports = [
            r for r in self._reports.values()
            if r.user_id == user_id
        ]
        
        if report_type:
            reports = [r for r in reports if r.report_type == report_type]
        
        return [
            {
                "report_id": r.report_id,
                "title": r.title,
                "type": r.report_type.value,
                "template": r.template.value,
                "generated_at": r.generated_at,
                "file_size_mb": r.file_size_bytes / (1024**2),
                "page_count": r.page_count,
                "file_path": str(r.file_path)
            }
            for r in sorted(reports, key=lambda x: x.generated_at, reverse=True)
        ]
    
    async def delete_report(self, report_id: str) -> bool:
        """Delete a generated report."""
        if report_id not in self._reports:
            return False
        
        report = self._reports[report_id]
        
        # Delete file
        if report.file_path.exists():
            report.file_path.unlink()
        
        del self._reports[report_id]
        return True
    
    def get_report_stats(self) -> Dict[str, Any]:
        """Get report generation statistics."""
        total = len(self._reports)
        
        by_type = {}
        for report in self._reports.values():
            t = report.report_type.value
            by_type[t] = by_type.get(t, 0) + 1
        
        total_size = sum(r.file_size_bytes for r in self._reports.values())
        
        return {
            "total_reports": total,
            "by_type": by_type,
            "total_size_mb": total_size / (1024**2),
            "storage_path": str(self.output_dir)
        }


# Global instance
_pdf_service: Optional[PDFReportService] = None


def get_pdf_report_service() -> PDFReportService:
    """Get global PDF report service."""
    global _pdf_service
    if _pdf_service is None:
        _pdf_service = PDFReportService()
    return _pdf_service


# Convenience functions
async def generate_analytics_report(
    user_id: str,
    title: str,
    data: Dict[str, Any],
    date_range: tuple
) -> str:
    """Quick analytics report generation."""
    service = get_pdf_report_service()
    report = await service.generate_report(
        user_id=user_id,
        report_type=ReportType.ANALYTICS,
        template=ReportTemplate.WEEKLY_ANALYTICS,
        title=title,
        data=data,
        date_range=date_range
    )
    return str(report.file_path)
