"""
Schema validation for script generation.

Validates LLM outputs against expected schemas
before creating Pydantic models.
"""

from typing import Any

from ..shared.exceptions import ValidationError
from ..shared.models import ShotType, CameraMovement, SceneType, CharacterTier


def validate_world_setting(data: dict) -> None:
    """
    Validate world setting data structure.

    Args:
        data: Dict from LLM response

    Raises:
        ValidationError: If validation fails
    """
    if not isinstance(data, dict):
        raise ValidationError("World setting must be a dictionary", "world_setting")

    # Validate characters
    characters = data.get("characters", [])
    if not isinstance(characters, list):
        raise ValidationError("Characters must be a list", "world_setting.characters")

    for i, char in enumerate(characters):
        _validate_character(char, f"world_setting.characters[{i}]")

    # Validate locations
    locations = data.get("locations", [])
    if not isinstance(locations, list):
        raise ValidationError("Locations must be a list", "world_setting.locations")

    for i, loc in enumerate(locations):
        _validate_location(loc, f"world_setting.locations[{i}]")

    # Validate props (optional)
    props = data.get("props", [])
    if not isinstance(props, list):
        raise ValidationError("Props must be a list", "world_setting.props")


def _validate_character(data: dict, path: str) -> None:
    """Validate character data"""
    required = ["id", "name", "description"]
    for field in required:
        if field not in data:
            raise ValidationError(f"Missing required field: {field}", path)

    # Validate tier if present
    if "tier" in data:
        try:
            CharacterTier(data["tier"])
        except ValueError:
            valid = [t.value for t in CharacterTier]
            raise ValidationError(
                f"Invalid tier: {data['tier']}. Must be one of {valid}",
                f"{path}.tier"
            )


def _validate_location(data: dict, path: str) -> None:
    """Validate location data"""
    required = ["id", "name", "description"]
    for field in required:
        if field not in data:
            raise ValidationError(f"Missing required field: {field}", path)


def validate_storyboard(data: dict) -> None:
    """
    Validate storyboard data structure.

    Args:
        data: Dict from LLM response

    Raises:
        ValidationError: If validation fails
    """
    if not isinstance(data, dict):
        raise ValidationError("Storyboard must be a dictionary", "storyboard")

    # Validate shots
    shots = data.get("shots", [])
    if not isinstance(shots, list):
        raise ValidationError("Shots must be a list", "storyboard.shots")

    if len(shots) == 0:
        raise ValidationError("Storyboard must have at least one shot", "storyboard.shots")

    for i, shot in enumerate(shots):
        _validate_shot(shot, f"storyboard.shots[{i}]")


def _validate_shot(data: dict, path: str) -> None:
    """Validate shot data"""
    required = ["shot_id", "visual_prompt"]
    for field in required:
        if field not in data:
            raise ValidationError(f"Missing required field: {field}", path)

    # Validate shot_id is int
    if not isinstance(data["shot_id"], int):
        raise ValidationError("shot_id must be an integer", f"{path}.shot_id")

    # Validate visual_prompt is non-empty string
    if not isinstance(data["visual_prompt"], str) or not data["visual_prompt"].strip():
        raise ValidationError("visual_prompt must be a non-empty string", f"{path}.visual_prompt")

    # Normalize and validate shot_type if present
    if "shot_type" in data:
        normalized = data["shot_type"].upper()
        try:
            ShotType(normalized)
            data["shot_type"] = normalized  # Update to normalized value
        except ValueError:
            valid = [t.value for t in ShotType]
            raise ValidationError(
                f"Invalid shot_type: {data['shot_type']}. Must be one of {valid}",
                f"{path}.shot_type"
            )

    # Normalize and validate camera_movement if present
    if "camera_movement" in data:
        normalized = data["camera_movement"].upper().replace("_", "").replace("-", "")
        # Map common variations to enum values
        movement_map = {
            "STATIC": "STATIC", "PUSHIN": "PUSH", "PUSH": "PUSH",
            "PULLOUT": "PULL", "PULL": "PULL",
            "PANLEFT": "PAN", "PANRIGHT": "PAN", "PAN": "PAN",
            "TILTUP": "TILT", "TILTDOWN": "TILT", "TILT": "TILT",
            "DOLLY": "DOLLY", "TRACK": "DOLLY", "TRACKING": "DOLLY",
            "CRANE": "CRANE", "HANDHELD": "HANDHELD", "ZOOM": "ZOOM",
        }
        mapped = movement_map.get(normalized)
        if mapped:
            data["camera_movement"] = mapped
        else:
            try:
                CameraMovement(normalized)
                data["camera_movement"] = normalized
            except ValueError:
                valid = [m.value for m in CameraMovement]
                raise ValidationError(
                    f"Invalid camera_movement: {data['camera_movement']}. Must be one of {valid}",
                    f"{path}.camera_movement"
                )

    # Validate scene_type if present (lowercase values)
    if "scene_type" in data:
        normalized = data["scene_type"].lower()
        try:
            SceneType(normalized)
            data["scene_type"] = normalized
        except ValueError:
            valid = [s.value for s in SceneType]
            raise ValidationError(
                f"Invalid scene_type: {data['scene_type']}. Must be one of {valid}",
                f"{path}.scene_type"
            )

    # Validate transition if present (uppercase values)
    if "transition" in data:
        from ..shared.models import Transition
        normalized = data["transition"].upper()
        try:
            Transition(normalized)
            data["transition"] = normalized
        except ValueError:
            valid = [t.value for t in Transition]
            raise ValidationError(
                f"Invalid transition: {data['transition']}. Must be one of {valid}",
                f"{path}.transition"
            )

    # Validate duration if present
    if "duration" in data:
        duration = data["duration"]
        if not isinstance(duration, (int, float)):
            raise ValidationError("duration must be a number", f"{path}.duration")
        if duration < 0.5 or duration > 60.0:
            raise ValidationError("duration must be between 0.5 and 60 seconds", f"{path}.duration")

    # Validate characters if present
    if "characters" in data:
        if not isinstance(data["characters"], list):
            raise ValidationError("characters must be a list", f"{path}.characters")


def validate_visual_prompt(prompt: str) -> None:
    """
    Validate a visual prompt string.

    Args:
        prompt: Visual prompt to validate

    Raises:
        ValidationError: If validation fails
    """
    if not prompt or not prompt.strip():
        raise ValidationError("Visual prompt cannot be empty", "visual_prompt")

    if len(prompt) > 2000:
        raise ValidationError(
            f"Visual prompt too long ({len(prompt)} chars). Max 2000 chars.",
            "visual_prompt"
        )
