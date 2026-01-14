"""
Prompt template manager.

Manages Jinja2 templates for LLM prompts,
supporting hot-reload without restarting.
"""

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, TemplateNotFound

from .logger import get_logger


logger = get_logger(__name__)


class PromptManager:
    """
    Prompt template manager using Jinja2.

    Templates are stored in separate .jinja2 files for easy iteration.
    Supports hot-reload for development.

    Usage:
        prompts = PromptManager("src/script/prompts")

        result = prompts.render(
            "storyboard.jinja2",
            world_setting=world_setting,
            script_content=text
        )
    """

    def __init__(self, template_dir: str = "src/script/prompts"):
        """
        Initialize prompt manager.

        Args:
            template_dir: Directory containing .jinja2 template files
        """
        self.template_dir = Path(template_dir)

        if not self.template_dir.exists():
            self.template_dir.mkdir(parents=True, exist_ok=True)
            logger.warning(f"Created template directory: {template_dir}")

        self.env = Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True
        )

    def render(self, template_name: str, **kwargs: Any) -> str:
        """
        Render a prompt template.

        Args:
            template_name: Name of the template file (e.g., "storyboard.jinja2")
            **kwargs: Variables to pass to the template

        Returns:
            Rendered prompt string
        """
        try:
            template = self.env.get_template(template_name)
            return template.render(**kwargs)
        except TemplateNotFound:
            logger.error(f"Template not found: {template_name}")
            raise FileNotFoundError(f"Prompt template not found: {self.template_dir / template_name}")

    def reload(self):
        """Clear template cache for hot-reload"""
        self.env.cache.clear() if hasattr(self.env, 'cache') else None
        logger.info("Prompt templates reloaded")

    def list_templates(self) -> list[str]:
        """List all available templates"""
        return [f.name for f in self.template_dir.glob("*.jinja2")]

    def get_template_path(self, template_name: str) -> Path:
        """Get full path to a template file"""
        return self.template_dir / template_name
