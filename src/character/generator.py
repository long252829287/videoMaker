"""
Character asset generation.

Generates character reference images using:
- SDXL/Flux for base generation
- LoRA training data preparation
- Reference Atlas for IP-Adapter
"""

from pathlib import Path
from typing import Optional

from ..shared.logger import get_logger
from ..shared.config import get_config
from ..shared.models import Character, CharacterTier
from ..shared.comfyui import ComfyWorkflow, ComfyUIClient
from ..shared.exceptions import ComfyUIError


logger = get_logger(__name__)


class CharacterGenerator:
    """
    Character reference image generator.

    Generates reference images for characters based on tier:
    - Tier 1: Full character sheet for LoRA training
    - Tier 2: Reference Atlas for IP-Adapter
    - Tier 3: Single reference for prompt guidance

    Reference Atlas includes multiple variants:
    - Different lighting (day, night, warm, cool)
    - Different expressions (if applicable)
    - Different angles (front, 3/4, profile)
    """

    # Workflow templates for different tiers
    WORKFLOWS = {
        CharacterTier.TIER1: "workflows/character_sheet.json",
        CharacterTier.TIER2: "workflows/character_reference.json",
        CharacterTier.TIER3: "workflows/character_simple.json",
    }

    # Reference Atlas lighting variants
    LIGHTING_VARIANTS = [
        "natural daylight, soft shadows",
        "warm sunset lighting, golden hour",
        "cool night lighting, blue tones",
        "studio lighting, neutral"
    ]

    def __init__(
        self,
        output_dir: str,
        comfyui_host: str = "127.0.0.1",
        comfyui_port: int = 8188
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.client = ComfyUIClient(comfyui_host, comfyui_port)
        self.config = get_config()

    def generate_reference(
        self,
        character: Character,
        global_style: Optional[str] = None,
        seed: Optional[int] = None
    ) -> dict:
        """
        Generate reference images for a character.

        Args:
            character: Character model with description
            global_style: Optional global style to apply
            seed: Random seed for reproducibility

        Returns:
            Dict with paths to generated images
        """
        if not self.client.is_available():
            raise ComfyUIError("ComfyUI server not available")

        tier = character.tier or CharacterTier.TIER3
        workflow_path = self.WORKFLOWS.get(tier)

        if not Path(workflow_path).exists():
            logger.warning(f"Workflow not found: {workflow_path}, using simple workflow")
            workflow_path = self.WORKFLOWS[CharacterTier.TIER3]

        results = {}

        if tier == CharacterTier.TIER1:
            results = self._generate_character_sheet(character, workflow_path, global_style, seed)
        elif tier == CharacterTier.TIER2:
            results = self._generate_reference_atlas(character, workflow_path, global_style, seed)
        else:
            results = self._generate_simple_reference(character, workflow_path, global_style, seed)

        return results

    def _generate_character_sheet(
        self,
        character: Character,
        workflow_path: str,
        global_style: Optional[str],
        seed: Optional[int]
    ) -> dict:
        """Generate full character sheet for LoRA training"""
        logger.info(f"Generating character sheet for: {character.name}")

        # Build workflow
        workflow = (
            ComfyWorkflow(workflow_path)
            .set_prompt(self._build_character_prompt(character))
            .set_seed(seed or 42)
        )

        if global_style:
            workflow.apply_global_style(global_style)

        # Submit and wait
        output = self.client.submit_and_wait(workflow.build(), timeout=300.0)

        # Save output images
        images = self._save_outputs(output, character.id, "sheet")

        return {
            "type": "character_sheet",
            "character_id": character.id,
            "images": images
        }

    def _generate_reference_atlas(
        self,
        character: Character,
        workflow_path: str,
        global_style: Optional[str],
        seed: Optional[int]
    ) -> dict:
        """Generate Reference Atlas with multiple lighting variants"""
        logger.info(f"Generating Reference Atlas for: {character.name}")

        images = []
        base_seed = seed or 42

        for i, lighting in enumerate(self.LIGHTING_VARIANTS):
            prompt = self._build_character_prompt(character)
            prompt = f"{prompt}, {lighting}"

            workflow = (
                ComfyWorkflow(workflow_path)
                .set_prompt(prompt)
                .set_seed(base_seed + i)
            )

            if global_style:
                workflow.apply_global_style(global_style)

            try:
                output = self.client.submit_and_wait(workflow.build(), timeout=180.0)
                saved = self._save_outputs(output, character.id, f"variant_{i}")
                images.extend(saved)
            except Exception as e:
                logger.warning(f"Failed to generate variant {i}: {e}")

        return {
            "type": "reference_atlas",
            "character_id": character.id,
            "images": images,
            "variants": len(images)
        }

    def _generate_simple_reference(
        self,
        character: Character,
        workflow_path: str,
        global_style: Optional[str],
        seed: Optional[int]
    ) -> dict:
        """Generate single reference image"""
        logger.info(f"Generating simple reference for: {character.name}")

        workflow = (
            ComfyWorkflow(workflow_path)
            .set_prompt(self._build_character_prompt(character))
            .set_seed(seed or 42)
        )

        if global_style:
            workflow.apply_global_style(global_style)

        output = self.client.submit_and_wait(workflow.build(), timeout=120.0)
        images = self._save_outputs(output, character.id, "ref")

        return {
            "type": "simple_reference",
            "character_id": character.id,
            "images": images
        }

    def _build_character_prompt(self, character: Character) -> str:
        """Build prompt from character description"""
        parts = [character.visual_description or character.description]

        # Add physical attributes if available
        if character.attributes:
            attrs = character.attributes
            if "age" in attrs:
                parts.append(f"{attrs['age']} years old")
            if "hair" in attrs:
                parts.append(f"{attrs['hair']} hair")
            if "clothing" in attrs:
                parts.append(attrs["clothing"])

        return ", ".join(parts)

    def _save_outputs(self, output: dict, char_id: str, suffix: str) -> list[str]:
        """Save ComfyUI outputs to disk"""
        saved_paths = []

        for node_id, node_output in output.items():
            if "images" not in node_output:
                continue

            for i, image_info in enumerate(node_output["images"]):
                filename = image_info.get("filename")
                if not filename:
                    continue

                # Download image from ComfyUI
                image_data = self.client.get_image(
                    filename,
                    subfolder=image_info.get("subfolder", ""),
                    folder_type=image_info.get("type", "output")
                )

                # Save locally
                output_path = self.output_dir / f"{char_id}_{suffix}_{i}.png"
                output_path.write_bytes(image_data)
                saved_paths.append(str(output_path))
                logger.debug(f"Saved: {output_path}")

        return saved_paths
