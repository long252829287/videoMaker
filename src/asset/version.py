"""
Asset version management.

Handles versioned file naming and retrieval,
preventing accidental overwrites during development.
"""

import json
from pathlib import Path
from typing import Optional

from ..shared.logger import get_logger


logger = get_logger(__name__)


def get_asset_path(
    project_id: str,
    shot_id: int,
    asset_type: str,
    extension: str,
    version: Optional[int] = None,
    base_dir: str = "storage/projects"
) -> str:
    """
    Generate versioned asset path.

    Auto-increments version number if not specified.

    Args:
        project_id: Project identifier
        shot_id: Shot number
        asset_type: Type of asset ("images", "audio", "video")
        extension: File extension without dot
        version: Specific version number (auto-detect if None)
        base_dir: Base storage directory

    Returns:
        Full path to the asset file

    Example:
        path = get_asset_path("proj_001", 1, "images", "png")
        # Returns: storage/projects/proj_001/assets/images/shot_001_v01.png
    """
    asset_dir = Path(base_dir) / project_id / "assets" / asset_type
    asset_dir.mkdir(parents=True, exist_ok=True)

    if version is None:
        # Find existing versions and increment
        pattern = f"shot_{shot_id:03d}_v*.{extension}"
        existing = list(asset_dir.glob(pattern))
        version = len(existing) + 1

    filename = f"shot_{shot_id:03d}_v{version:02d}.{extension}"
    return str(asset_dir / filename)


def get_latest_asset(
    project_id: str,
    shot_id: int,
    asset_type: str,
    extension: str,
    base_dir: str = "storage/projects"
) -> Optional[str]:
    """
    Get the latest version of an asset.

    Args:
        project_id: Project identifier
        shot_id: Shot number
        asset_type: Type of asset
        extension: File extension

    Returns:
        Path to the latest version, or None if not found
    """
    asset_dir = Path(base_dir) / project_id / "assets" / asset_type
    pattern = f"shot_{shot_id:03d}_v*.{extension}"

    files = sorted(asset_dir.glob(pattern))
    return str(files[-1]) if files else None


def get_all_versions(
    project_id: str,
    shot_id: int,
    asset_type: str,
    extension: str,
    base_dir: str = "storage/projects"
) -> list[str]:
    """
    Get all versions of an asset.

    Returns:
        List of paths to all versions, sorted by version number
    """
    asset_dir = Path(base_dir) / project_id / "assets" / asset_type
    pattern = f"shot_{shot_id:03d}_v*.{extension}"

    return [str(f) for f in sorted(asset_dir.glob(pattern))]


def get_selected_asset(
    project_id: str,
    shot_id: int,
    asset_type: str,
    base_dir: str = "storage/projects"
) -> Optional[str]:
    """
    Get the user-selected version of an asset.

    Selection is stored in selection.json in the project directory.

    Returns:
        Path to selected version, or None if not selected
    """
    selection_file = Path(base_dir) / project_id / "selection.json"

    if not selection_file.exists():
        return None

    try:
        selections = json.loads(selection_file.read_text())
        key = f"{asset_type}/shot_{shot_id:03d}"
        return selections.get(key)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Failed to read selection.json: {e}")
        return None


def set_selected_asset(
    project_id: str,
    shot_id: int,
    asset_type: str,
    asset_path: str,
    base_dir: str = "storage/projects"
) -> None:
    """
    Set the selected version for an asset.

    Args:
        project_id: Project identifier
        shot_id: Shot number
        asset_type: Type of asset
        asset_path: Path to the selected version
    """
    selection_file = Path(base_dir) / project_id / "selection.json"

    # Load existing selections
    if selection_file.exists():
        try:
            selections = json.loads(selection_file.read_text())
        except (json.JSONDecodeError, IOError):
            selections = {}
    else:
        selections = {}

    # Update selection
    key = f"{asset_type}/shot_{shot_id:03d}"
    selections[key] = asset_path

    # Save
    selection_file.write_text(json.dumps(selections, indent=2))
    logger.info(f"Selected {asset_path} for {key}")
