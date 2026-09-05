"""Head/CSS half of the default invitation HTML template.

Split out purely to keep default_template.py under the file-length limit —
this is one HTML/CSS literal cut at the </style> boundary, not independent
logic.
"""

TEMPLATE_HEAD = """
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
                    background: linear-gradient(135deg, #0D1B5A 0%, #1E3A8A 60%, #2D7DFF 100%);
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
                    background-color: #F4F6FB;
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
                    background-color: #2D7DFF;
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
                    background-color: #1E3A8A;
                }}
                .link-fallback {{
                    font-size: 14px;
                    color: #555;
                    margin-top: 10px;
                    word-break: break-all;
                }}
                .link-fallback a {{
                    color: #2D7DFF;
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
"""
