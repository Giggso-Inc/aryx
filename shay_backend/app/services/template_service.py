"""
Template service for fetching and processing email templates.

This module provides functionality to fetch template content by template_id
and process templates for email invitations.

Author: AI Assistant
Date: 2025-01-27
Version: 1.0.0
"""

import os
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status

from app.models.template import Template
from app.core.config import settings


class TemplateService:
    """Service for managing email templates"""
    
    def __init__(self):
        """Initialize template service"""
        self.template_dir = settings.TEMPLATE_DIR
    
    async def get_template_content(
        self, 
        template_id: str, 
        db: AsyncSession
    ) -> Dict[str, Any]:
        """
        Fetch template content by template_id
        
        Args:
            template_id: Template ID to fetch
            db: Database session
            
        Returns:
            Dict containing template content and metadata
            
        Raises:
            HTTPException: If template not found or file read error
        """
        try:
            # Find template record by template_id
            result = await db.execute(
                select(Template).where(Template.template_id == template_id)
            )
            template = result.scalar_one_or_none()
            
            if not template:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Template not found: {template_id}"
                )
            
            # Get file path from database record
            file_path = template.file_path
            if not file_path:
                # Fallback to template directory + template_name
                file_path = os.path.join(self.template_dir, template.template_name)
            
            # Check if file exists
            if not os.path.exists(file_path):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Template file not found: {file_path}"
                )
            
            # Security check - ensure file is within template directory
            if not os.path.abspath(file_path).startswith(os.path.abspath(self.template_dir)):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied: File path outside template directory"
                )
            
            # Read file content
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            return {
                'template_id': template.template_id,
                'template_name': template.template_name,
                'content': content,
                'file_path': file_path,
                'additional_config': template.additional_config or {}
            }
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error fetching template content: {str(e)}"
            )
    
    def process_template_content(
        self, 
        template_content: str, 
        variables: Dict[str, Any]
    ) -> str:
        """
        Process template content with variables
        
        Args:
            template_content: Raw template content
            variables: Dictionary of variables to substitute
            
        Returns:
            Processed template content
        """
        try:
            # Use string replacement to avoid issues with CSS and other curly braces
            # This is safer than str.format() which interprets all {text} as format placeholders
            processed_content = template_content
            
            for key, value in variables.items():
                placeholder = f"{{{key}}}"
                processed_content = processed_content.replace(placeholder, str(value))
            
            return processed_content
        except Exception as e:
            raise ValueError(f"Error processing template: {str(e)}")
    
    def get_default_invitation_template(self) -> str:
        """
        Get default invitation template if no template_id is provided
        
        Returns:
            Default HTML invitation template
        """
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Welcome to {platform_name}</title>
            <style>
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    background-color: #f8f9fa;
                    color: #0f1729;
                    margin: 0;
                    padding: 0;
                }}
                .email-wrapper {{
                    max-width: 600px;
                    margin: 40px auto;
                    background: #ffffff;
                    border-radius: 10px;
                    box-shadow: 0 4px 10px rgba(0, 0, 0, 0.08);
                    overflow: hidden;
                }}
                .email-header {{
                    background-color: #2a6df4;
                    color: #fff;
                    text-align: center;
                    padding: 24px 20px;
                }}
                .email-header h1 {{
                    margin: 0;
                    font-size: 22px;
                    font-weight: 700;
                    color: #ffffff;
                }}
                .email-header p {{
                    margin: 8px 0 0;
                    font-size: 14px;
                    opacity: 0.95;
                    color: #ffffff;
                }}
                .email-body {{
                    padding: 36px 30px;
                }}
                .greeting {{
                    font-size: 18px;
                    font-weight: 600;
                    margin-bottom: 16px;
                }}
                .message {{
                    font-size: 15px;
                    line-height: 1.7;
                    margin-bottom: 22px;
                }}
                .product-intro {{
                    background-color: #f1f5f9;
                    border-radius: 8px;
                    padding: 16px 20px;
                    margin: 24px 0;
                }}
                .product-intro p {{
                    margin: 0;
                    font-size: 14px;
                    color: #0f1729;
                }}
                .cta-button {{
                    display: inline-block;
                    background-color: #2a6df4;
                    color: #fff;
                    text-decoration: none;
                    padding: 14px 32px;
                    border-radius: 50px;
                    font-weight: 600;
                    font-size: 15px;
                    text-align: center;
                    margin: 30px auto;
                    transition: background 0.3s ease;
                }}
                .cta-button:hover {{
                    background-color: #1f56c1;
                }}
                .link-fallback {{
                    font-size: 14px;
                    color: #555;
                    margin-top: 10px;
                    word-break: break-all;
                }}
                .link-fallback a {{
                    color: #2a6df4;
                    text-decoration: none;
                }}
                .warning {{
                    background-color: #fff8e1;
                    border-radius: 8px;
                    padding: 14px 18px;
                    margin: 28px 0;
                    font-size: 14px;
                    color: #c47f08;
                }}
                .footer {{
                    background: #f8f9fa;
                    padding: 30px;
                    text-align: center;
                    border-top: 1px solid #e9ecef;
                }}
                .footer p {{
                    margin: 0 0 10px 0;
                    color: #0f1729;
                    font-size: 14px;
                }}
                .footer .company-info {{
                    color: #0f1729;
                    font-weight: 500;
                }}
                @media (max-width: 600px) {{
                    .email-body {{
                        padding: 28px 20px;
                    }}
                    .cta-button {{
                        width: 100%;
                    }}
                }}
            </style>
        </head>
        <body>
            <div class="email-wrapper">
                    <div class="email-header">
                        <h1>Welcome to {platform_name}</h1>
                        <p>You're one step away from joining {company_name}</p>
                    </div>
                    <div class="email-body">
                        <p class="greeting">Hello {user_name},</p>
                        
                        <p class="message">
                            Great news! <strong>{invited_by}</strong> has invited you to join {company_name} on <strong>{platform_name}</strong>.
                            Accept the invitation below to start collaborating with your team.
                        </p>
                        
                        <div class="product-intro">
                            <p>
                                {platform_name} helps teams collaborate effectively with secure access, guided workflows, and powerful automation to keep everyone aligned.
                            </p>
                        </div>
                        
                        <div style="text-align:center;">
                            <a href="{registration_short_link}" class="cta-button">Accept Invitation</a>
                        </div>
                        
                        <div class="link-fallback">
                            Can’t click the button? Copy and paste this link into your browser:<br/>
                            <a href="{registration_short_link}">{registration_short_link}</a>
                        </div>
                        
                        <p class="message">
                            If you need assistance, please contact your team administrator.
                        </p>
                        
                        <div class="warning">
                            ⚠️ <strong>Security Notice:</strong> This invitation will expire in {expires_at}.
                        </div>
                    </div>
                    
                    <div class="footer">
                        <p>If you didn’t expect this invitation, you can safely ignore this email.</p>
                        <p class="company-info">© {current_year} {platform_name}. All rights reserved.</p>
                    </div>
            </div>
        </body>
        </html>
        """


# Create a singleton instance
template_service = TemplateService()





