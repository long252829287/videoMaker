"""
Pipeline checkpoint management.

Provides save/restore functionality for pipeline state,
enabling resume after interruption.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Optional

from ..shared.logger import get_logger
from ..shared.models import ProjectState


logger = get_logger(__name__)


class CheckpointManager:
    """
    Pipeline checkpoint manager.

    Saves and restores pipeline state to enable:
    - Resume after failure
    - Continue from specific stage
    - Debug and inspect intermediate states

    Checkpoints are stored as JSON files.
    """

    def __init__(self, checkpoint_dir: str):
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def _get_checkpoint_path(self, project_id: str) -> Path:
        """Get checkpoint file path for a project"""
        return self.checkpoint_dir / f"{project_id}_checkpoint.json"

    def save(self, project_id: str, state: ProjectState) -> str:
        """
        Save pipeline state to checkpoint.

        Args:
            project_id: Project identifier
            state: Current pipeline state

        Returns:
            Path to saved checkpoint file
        """
        checkpoint_path = self._get_checkpoint_path(project_id)

        checkpoint_data = {
            "project_id": project_id,
            "timestamp": datetime.now().isoformat(),
            "state": state.model_dump()
        }

        with open(checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(checkpoint_data, f, indent=2, ensure_ascii=False)

        logger.debug(f"Checkpoint saved: {checkpoint_path}")
        return str(checkpoint_path)

    def load(self, project_id: str) -> Optional[ProjectState]:
        """
        Load pipeline state from checkpoint.

        Args:
            project_id: Project identifier

        Returns:
            ProjectState if checkpoint exists, None otherwise
        """
        checkpoint_path = self._get_checkpoint_path(project_id)

        if not checkpoint_path.exists():
            logger.debug(f"No checkpoint found for: {project_id}")
            return None

        try:
            with open(checkpoint_path, "r", encoding="utf-8") as f:
                checkpoint_data = json.load(f)

            state = ProjectState(**checkpoint_data["state"])
            logger.info(f"Checkpoint loaded: {checkpoint_path}")
            return state

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"Failed to load checkpoint: {e}")
            return None

    def delete(self, project_id: str) -> bool:
        """
        Delete checkpoint for a project.

        Args:
            project_id: Project identifier

        Returns:
            True if deleted, False if not found
        """
        checkpoint_path = self._get_checkpoint_path(project_id)

        if checkpoint_path.exists():
            checkpoint_path.unlink()
            logger.info(f"Checkpoint deleted: {checkpoint_path}")
            return True

        return False

    def exists(self, project_id: str) -> bool:
        """Check if checkpoint exists for a project"""
        return self._get_checkpoint_path(project_id).exists()

    def list_checkpoints(self) -> list[dict]:
        """
        List all available checkpoints.

        Returns:
            List of checkpoint info dicts
        """
        checkpoints = []

        for path in self.checkpoint_dir.glob("*_checkpoint.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    checkpoints.append({
                        "project_id": data.get("project_id"),
                        "timestamp": data.get("timestamp"),
                        "path": str(path)
                    })
            except (json.JSONDecodeError, IOError):
                continue

        return sorted(checkpoints, key=lambda x: x.get("timestamp", ""), reverse=True)

    def get_checkpoint_info(self, project_id: str) -> Optional[dict]:
        """
        Get checkpoint metadata without loading full state.

        Returns:
            Dict with checkpoint info, or None if not found
        """
        checkpoint_path = self._get_checkpoint_path(project_id)

        if not checkpoint_path.exists():
            return None

        try:
            with open(checkpoint_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            return {
                "project_id": data.get("project_id"),
                "timestamp": data.get("timestamp"),
                "current_stage": data.get("state", {}).get("current_stage"),
                "completed_stages": data.get("state", {}).get("completed_stages", []),
                "path": str(checkpoint_path)
            }
        except (json.JSONDecodeError, IOError):
            return None
