"""Substitute {placeholder} variables into template text."""

from typing import Any, Dict


class ProcessMixin:
    """Simple string-replace based template variable substitution."""

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
