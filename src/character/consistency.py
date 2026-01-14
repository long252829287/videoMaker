"""
Character consistency management.

Ensures visual consistency across shots using:
- IP-Adapter for reference-based generation
- LoRA for trained character features
- Prompt augmentation for style consistency
"""

from pathlib import Path
from typing import Optional

from ..shared.logger import get_logger
from ..shared.models import Character, CharacterTier, Shot
from ..shared.comfyui import ComfyWorkflow


logger = get_logger(__name__)


class ConsistencyManager:
    """
    Character consistency manager.

    Applies character references to shot generation:
    - Tier 1: LoRA + IP-Adapter
    - Tier 2: IP-Adapter only
    - Tier 3: Prompt injection

    Also manages global style injection.
    """

    def __init__(self, reference_dir: str):
        """
        Initialize consistency manager.

        Args:
            reference_dir: Directory containing character references
        """
        self.reference_dir = Path(reference_dir)
        self._character_cache: dict[str, CharacterReference] = {}

    def load_character_reference(self, character: Character) -> "CharacterReference":
        """
        Load or create character reference data.

        Args:
            character: Character model

        Returns:
            CharacterReference with paths to assets
        """
        if character.id in self._character_cache:
            return self._character_cache[character.id]

        ref = CharacterReference(
            character_id=character.id,
            tier=character.tier or CharacterTier.TIER3
        )

        char_dir = self.reference_dir / character.id

        # Find LoRA file
        lora_files = list(char_dir.glob("*.safetensors")) if char_dir.exists() else []
        if lora_files:
            ref.lora_path = str(lora_files[0])
            ref.lora_name = lora_files[0].name

        # Find reference images
        if char_dir.exists():
            ref.reference_images = [
                str(p) for p in char_dir.glob("*.png")
            ]

        self._character_cache[character.id] = ref
        return ref

    def apply_to_workflow(
        self,
        workflow: ComfyWorkflow,
        characters: list[Character],
        global_style: Optional[str] = None
    ) -> ComfyWorkflow:
        """
        Apply character consistency to workflow.

        Args:
            workflow: ComfyWorkflow to modify
            characters: Characters appearing in the shot
            global_style: Optional global style

        Returns:
            Modified ComfyWorkflow
        """
        # Apply global style first
        if global_style:
            workflow.apply_global_style(global_style)

        # Apply character-specific modifications
        for character in characters:
            ref = self.load_character_reference(character)

            if ref.tier == CharacterTier.TIER1 and ref.lora_path:
                # Apply LoRA
                workflow.set_lora(ref.lora_name, strength=0.8)
                logger.debug(f"Applied LoRA for {character.id}: {ref.lora_name}")

                # Also apply IP-Adapter reference if available
                if ref.reference_images:
                    self._apply_ip_adapter(workflow, ref.reference_images[0])

            elif ref.tier == CharacterTier.TIER2 and ref.reference_images:
                # Apply IP-Adapter only
                self._apply_ip_adapter(workflow, ref.reference_images[0])
                logger.debug(f"Applied IP-Adapter for {character.id}")

            # Tier 3: No specific application, relies on prompt

        return workflow

    def _apply_ip_adapter(self, workflow: ComfyWorkflow, image_path: str) -> None:
        """Apply IP-Adapter reference image to workflow"""
        # Set the reference image for IP-Adapter node
        workflow._set_node_input("IPAdapter", "image", image_path)
        workflow._set_node_input("IPAdapterApply", "weight", 0.7)

    def augment_prompt(
        self,
        base_prompt: str,
        characters: list[Character],
        global_style: Optional[str] = None
    ) -> str:
        """
        Augment prompt with character descriptions and style.

        Used for Tier 3 characters or when IP-Adapter is not available.

        Args:
            base_prompt: Original visual prompt
            characters: Characters in the shot
            global_style: Optional global style

        Returns:
            Augmented prompt string
        """
        parts = [base_prompt]

        # Add character descriptions
        for char in characters:
            if char.visual_description:
                parts.append(char.visual_description)
            elif char.description:
                # Extract visual elements from description
                parts.append(f"({char.name}: {char.description})")

        # Add global style
        if global_style:
            parts.append(global_style)

        return ", ".join(parts)

    def get_best_reference_image(
        self,
        character: Character,
        lighting: Optional[str] = None
    ) -> Optional[str]:
        """
        Get the best reference image for a character.

        If lighting is specified, tries to match Reference Atlas variant.

        Args:
            character: Character model
            lighting: Optional lighting condition to match

        Returns:
            Path to best reference image, or None
        """
        ref = self.load_character_reference(character)

        if not ref.reference_images:
            return None

        if lighting and len(ref.reference_images) > 1:
            # Try to match lighting variant
            # Reference Atlas naming: char_id_variant_0.png, variant_1.png, etc.
            lighting_map = {
                "day": 0,
                "sunset": 1,
                "night": 2,
                "studio": 3
            }

            for key, idx in lighting_map.items():
                if key in lighting.lower() and idx < len(ref.reference_images):
                    return ref.reference_images[idx]

        # Default to first image
        return ref.reference_images[0]


class CharacterReference:
    """Character reference data container"""

    def __init__(
        self,
        character_id: str,
        tier: CharacterTier = CharacterTier.TIER3
    ):
        self.character_id = character_id
        self.tier = tier
        self.lora_path: Optional[str] = None
        self.lora_name: Optional[str] = None
        self.reference_images: list[str] = []

    @property
    def has_lora(self) -> bool:
        return self.lora_path is not None

    @property
    def has_references(self) -> bool:
        return len(self.reference_images) > 0
