"""
InboundCheck - AI Content Intelligence REST Router (v1)
======================================================
Endpoints for template spam risk diagnostics and polymorphic copy generation.
"""

from fastapi import APIRouter, HTTPException, Query, status, Depends
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import logging

from app.core.security import get_current_user_id
from app.services.ai.content_optimizer import ai_content_service, DEFAULT_SAMPLE_TEMPLATES

logger = logging.getLogger("AIRoutes")

router = APIRouter(prefix="/ai", tags=["AI Content Lab"])


class TemplateAnalyzeRequest(BaseModel):
    subject: str = Field(..., description="Email subject line")
    body_content: str = Field(..., description="Email body text or HTML template")
    template_name: Optional[str] = "Shopify Order Template"


class PolymorphicGenerateRequest(BaseModel):
    subject: str = Field(..., description="Original subject line")
    body_content: str = Field(..., description="Original HTML/text content")


@router.get("/sample-templates")
async def get_sample_templates(user_id: str = Depends(get_current_user_id)):
    """
    Return preset Shopify transactional templates for instant testing.
    """
    return {"success": True, "templates": DEFAULT_SAMPLE_TEMPLATES}


@router.post("/analyze-template")
async def analyze_email_template(
    payload: TemplateAnalyzeRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    Audit template content for spam trigger density, formatting anomalies, and risk score.
    """
    try:
        result = await ai_content_service.analyze_template(
            subject=payload.subject,
            body_content=payload.body_content
        )
        return {
            "success": True,
            "template_name": payload.template_name,
            "audit": result
        }
    except Exception as e:
        logger.error(f"Error analyzing template: {e}")
        raise HTTPException(status_code=500, detail="Failed to analyze email template deliverability")


@router.post("/generate-polymorphic-variants")
async def generate_polymorphic_variants(
    payload: PolymorphicGenerateRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    Generate 3 deliverability-optimized polymorphic variations of the email copy.
    """
    try:
        variants = await ai_content_service.generate_polymorphic_variants(
            subject=payload.subject,
            body_content=payload.body_content
        )
        return {
            "success": True,
            "variants": variants
        }
    except Exception as e:
        logger.error(f"Error generating polymorphic variants: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate deliverability-optimized variants")
