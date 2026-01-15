"""
Shot image generation.

Generates images for storyboard shots using ComfyUI.
"""

import time
from pathlib import Path
from typing import Optional

from ..shared.logger import get_logger
from ..shared.config import get_config
from ..shared.models import Shot, WorldSetting, Character
from ..shared.comfyui import ComfyWorkflow, ComfyUIClient
from ..shared.exceptions import ComfyUIError
from ..character.consistency import ConsistencyManager
from .version import get_asset_path, get_all_versions


logger = get_logger(__name__)


class ImageGenerator:
    """
    Shot image generator.

    Generates images for storyboard shots with:
    - Character consistency via LoRA/IP-Adapter
    - Global style injection
    - Asset versioning
    """

    DEFAULT_WORKFLOW = "workflows/shot_image.json"

    def __init__(
        self,
        project_id: str,
        output_dir: str = "storage/projects",
        comfyui_host: str = "127.0.0.1",
        comfyui_port: int = 8188
    ):
        self.project_id = project_id
        self.output_dir = output_dir
        self.client = ComfyUIClient(comfyui_host, comfyui_port)
        self.config = get_config()
        self.consistency_manager: Optional[ConsistencyManager] = None

    def set_consistency_manager(self, manager: ConsistencyManager) -> None:
        """Set the consistency manager for character handling"""
        self.consistency_manager = manager

    def generate_shot_image(
        self,
        shot: Shot,
        world_setting: WorldSetting,
        global_style: Optional[str] = None,
        workflow_path: Optional[str] = None,
        seed: Optional[int] = None
    ) -> dict:
        """
        Generate image for a single shot.

        Args:
            shot: Shot to generate image for
            world_setting: World setting with character/location info
            global_style: Optional global style
            workflow_path: Custom workflow path
            seed: Random seed

        Returns:
            Dict with image path and metadata
        """
        start_time = time.time()

        if not self.client.is_available():
            raise ComfyUIError("ComfyUI server not available")

        # Determine workflow
        workflow_path = workflow_path or self.DEFAULT_WORKFLOW
        if not Path(workflow_path).exists():
            raise FileNotFoundError(f"Workflow not found: {workflow_path}")

        # Get characters for this shot
        characters = []
        for char_id in shot.characters:
            char = world_setting.get_character(char_id)
            if char:
                characters.append(char)

        # Build workflow
        workflow = ComfyWorkflow(workflow_path)
        workflow.set_prompt(shot.visual_prompt)
        workflow.set_seed(seed or shot.shot_id * 1000)

        # Apply consistency
        if self.consistency_manager and characters:
            workflow = self.consistency_manager.apply_to_workflow(
                workflow, characters, global_style
            )
        elif global_style:
            workflow.apply_global_style(global_style)

        # Set dimensions from config
        workflow.set_size(
            self.config.video.width,
            self.config.video.height
        )

        # Submit and wait
        logger.info(f"Generating image for shot {shot.shot_id}")
        output = self.client.submit_and_wait(workflow.build(), timeout=900.0)

        # Get versioned output path
        output_path = get_asset_path(
            self.project_id,
            shot.shot_id,
            "images",
            "png",
            base_dir=self.output_dir
        )

        # Save output
        saved_path = self._save_output(output, output_path)
        duration = time.time() - start_time

        return {
            "shot_id": shot.shot_id,
            "image_path": saved_path,
            "seed": seed or shot.shot_id * 1000,
            "duration_seconds": duration,
            "versions": get_all_versions(
                self.project_id,
                shot.shot_id,
                "images",
                "png",
                base_dir=self.output_dir
            )
        }

    def generate_batch(
        self,
        shots: list[Shot],
        world_setting: WorldSetting,
        global_style: Optional[str] = None
    ) -> list[dict]:
        """
        Generate images for multiple shots.

        Executes serially for VRAM safety (Phase 1).

        Args:
            shots: List of shots to generate
            world_setting: World setting
            global_style: Optional global style

        Returns:
            List of generation results
        """
        results = []

        for shot in shots:
            try:
                result = self.generate_shot_image(
                    shot=shot,
                    world_setting=world_setting,
                    global_style=global_style
                )
                results.append(result)
                logger.info(f"Shot {shot.shot_id} completed: {result['image_path']}")

            except Exception as e:
                logger.error(f"Shot {shot.shot_id} failed: {e}")
                results.append({
                    "shot_id": shot.shot_id,
                    "error": str(e),
                    "success": False
                })

        return results

    def regenerate_shot(
        self,
        shot: Shot,
        world_setting: WorldSetting,
        global_style: Optional[str] = None,
        seed: Optional[int] = None
    ) -> dict:
        """
        Regenerate a shot with new version.

        Args:
            shot: Shot to regenerate
            world_setting: World setting
            global_style: Optional global style
            seed: New seed (if None, random)

        Returns:
            Generation result with new version
        """
        import random
        new_seed = seed or random.randint(1, 999999)

        return self.generate_shot_image(
            shot=shot,
            world_setting=world_setting,
            global_style=global_style,
            seed=new_seed
        )

    def _save_output(self, output: dict, target_path: str) -> str:
        """Save ComfyUI output to target path"""
        for node_id, node_output in output.items():
            if "images" not in node_output:
                continue

            for image_info in node_output["images"]:
                filename = image_info.get("filename")
                if not filename:
                    continue

                # Download from ComfyUI
                image_data = self.client.get_image(
                    filename,
                    subfolder=image_info.get("subfolder", ""),
                    folder_type=image_info.get("type", "output")
                )

                # Save to target path
                Path(target_path).parent.mkdir(parents=True, exist_ok=True)
                Path(target_path).write_bytes(image_data)
                logger.debug(f"Saved image: {target_path}")

                return target_path

        raise ComfyUIError("No image in ComfyUI output")
