#!/usr/bin/env python3
"""
AI Video Automation System - CLI Entry Point

Usage:
    python main.py --input story.txt --output ./output
    python main.py script --input story.txt
    python main.py resume --project-id xxx --from-step assets
"""

import json
import click
import sys
from pathlib import Path
from datetime import datetime

# Load .env file before any config is read
from dotenv import load_dotenv
load_dotenv()

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.shared.config import get_config
from src.shared.logger import get_logger
from src.shared.models import ProjectState
from src.shared.comfyui import ComfyUIClient
from src.script.generator import ScriptGenerator
from src.asset.image import ImageGenerator
from src.asset.audio import AudioGenerator
from src.composer.timeline import TimelineBuilder
from src.composer.subtitle import SubtitleGenerator
from src.composer.mixer import Mixer
from src.render.encoder import VideoEncoder
from src.debug.reporter import DebugReporter
from src.pipeline.checkpoint import CheckpointManager


logger = get_logger(__name__)


@click.group(invoke_without_command=True)
@click.option("--input", "-i", "input_file", type=click.Path(exists=True), help="Input text file")
@click.option("--output", "-o", "output_dir", type=click.Path(), default="./output", help="Output directory")
@click.option("--config", "-c", "config_file", type=click.Path(), help="Config file path")
@click.option("--debug", is_flag=True, help="Enable debug mode")
@click.option("--dry-run", is_flag=True, help="Generate plan only, don't execute")
@click.pass_context
def cli(ctx, input_file, output_dir, config_file, debug, dry_run):
    """AI Video Automation System - Generate videos from text automatically."""
    ctx.ensure_object(dict)
    ctx.obj["debug"] = debug
    ctx.obj["dry_run"] = dry_run

    if ctx.invoked_subcommand is None:
        if input_file:
            # Run full pipeline
            click.echo(f"Starting full pipeline...")
            click.echo(f"  Input: {input_file}")
            click.echo(f"  Output: {output_dir}")
            click.echo(f"  Debug: {debug}")
            click.echo(f"  Dry Run: {dry_run}")

            # TODO: Implement full pipeline
            run_full_pipeline(input_file, output_dir, debug, dry_run)
        else:
            click.echo(ctx.get_help())


@cli.command()
@click.option("--input", "-i", "input_file", type=click.Path(exists=True), required=True)
@click.option("--output", "-o", "output_dir", type=click.Path(), default="./output")
@click.pass_context
def script(ctx, input_file, output_dir):
    """Generate storyboard script from input text."""
    click.echo(f"Generating script from: {input_file}")
    # TODO: Implement script generation
    click.echo("Script generation not yet implemented.")


@cli.command()
@click.option("--project-id", "-p", required=True, help="Project ID")
@click.pass_context
def character(ctx, project_id):
    """Generate character assets for a project."""
    click.echo(f"Generating characters for project: {project_id}")
    # TODO: Implement character generation
    click.echo("Character generation not yet implemented.")


@cli.command()
@click.option("--project-id", "-p", required=True, help="Project ID")
@click.pass_context
def assets(ctx, project_id):
    """Generate image/audio/video assets."""
    click.echo(f"Generating assets for project: {project_id}")
    # TODO: Implement asset generation
    click.echo("Asset generation not yet implemented.")


@cli.command()
@click.option("--project-id", "-p", required=True, help="Project ID")
@click.pass_context
def compose(ctx, project_id):
    """Compose video from assets."""
    click.echo(f"Composing video for project: {project_id}")
    # TODO: Implement video composition
    click.echo("Video composition not yet implemented.")


@cli.command()
@click.option("--project-id", "-p", required=True, help="Project ID")
@click.pass_context
def render(ctx, project_id):
    """Render final video output."""
    click.echo(f"Rendering video for project: {project_id}")
    # TODO: Implement video rendering
    click.echo("Video rendering not yet implemented.")


@cli.command()
@click.option("--project-id", "-p", required=True, help="Project ID")
@click.option("--from-step", "-f", required=True, help="Step to resume from")
@click.pass_context
def resume(ctx, project_id, from_step):
    """Resume pipeline from a checkpoint."""
    click.echo(f"Resuming project {project_id} from step: {from_step}")
    # TODO: Implement resume functionality
    click.echo("Resume not yet implemented.")


@cli.command()
@click.option("--project-id", "-p", required=True, help="Project ID")
@click.pass_context
def status(ctx, project_id):
    """Show project status."""
    click.echo(f"Project Status: {project_id}")
    # TODO: Implement status display
    click.echo("Status display not yet implemented.")


def run_full_pipeline(input_file: str, output_dir: str, debug: bool, dry_run: bool):
    """Run the full video generation pipeline."""
    config = get_config()

    # Create project
    project_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    project_dir = Path(config.paths.projects_dir) / project_id
    project_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Created project: {project_id}")
    logger.info(f"Project directory: {project_dir}")

    # Initialize debug reporter
    reporter = DebugReporter(project_id, str(project_dir))

    # Initialize checkpoint manager
    checkpoint_mgr = CheckpointManager(str(project_dir / "checkpoints"))

    # Read input text
    input_text = Path(input_file).read_text(encoding="utf-8")
    click.echo(f"\nInput text ({len(input_text)} chars):")
    click.echo(f"  {input_text[:100]}..." if len(input_text) > 100 else f"  {input_text}")

    # Initialize project state
    state = ProjectState(
        project_id=project_id,
        input_text=input_text,
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
    )

    if dry_run:
        click.echo("\n[Dry Run] Pipeline stages:")
        click.echo("  1. Script Generation - Generate storyboard from text")
        click.echo("  2. Character Generation - Create character assets")
        click.echo("  3. Asset Generation - Generate images, audio, video")
        click.echo("  4. Video Composition - Assemble timeline")
        click.echo("  5. Render - Encode final video")
        return

    try:
        # ========== Stage 1: Script Generation ==========
        click.echo("\n" + "="*50)
        click.echo("Stage 1: Script Generation")
        click.echo("="*50)
        reporter.add_stage_result("script", "running")

        script_gen = ScriptGenerator()

        # Generate world setting
        click.echo("  Generating world setting...")
        world_setting = script_gen.generate_world_setting(input_text)
        world_setting_path = project_dir / "world_setting.json"
        world_setting_path.write_text(
            json.dumps(world_setting.model_dump(), indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        click.echo(f"  ✓ World setting saved: {world_setting_path}")
        click.echo(f"    - {len(world_setting.characters)} characters")
        click.echo(f"    - {len(world_setting.locations)} locations")

        # Generate storyboard
        click.echo("  Generating storyboard...")
        storyboard = script_gen.generate_storyboard(
            input_text,
            world_setting,
            global_style=config.video.global_style if hasattr(config.video, 'global_style') else None
        )
        storyboard_path = project_dir / "storyboard.json"
        storyboard_path.write_text(
            json.dumps(storyboard.model_dump(), indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        click.echo(f"  ✓ Storyboard saved: {storyboard_path}")
        click.echo(f"    - {len(storyboard.shots)} shots")

        state.current_stage = "script"
        state.completed_stages.append("script")
        reporter.add_stage_result("script", "success")
        checkpoint_mgr.save(project_id, state)

        # ========== Stage 2: Asset Generation (Images + Audio) ==========
        click.echo("\n" + "="*50)
        click.echo("Stage 2: Asset Generation")
        click.echo("="*50)
        reporter.add_stage_result("assets", "running")

        # Check ComfyUI availability
        comfyui = ComfyUIClient(config.comfyui.host, config.comfyui.port)
        if not comfyui.is_available():
            click.echo("  ⚠ ComfyUI not available, skipping image generation")
            click.echo(f"    Please start ComfyUI at {config.comfyui.host}:{config.comfyui.port}")
            image_results = []
        else:
            click.echo("  ✓ ComfyUI connected")
            # Generate images
            image_gen = ImageGenerator(
                project_id=project_id,
                output_dir=config.paths.projects_dir,
                comfyui_host=config.comfyui.host,
                comfyui_port=config.comfyui.port
            )
            click.echo(f"  Generating images for {len(storyboard.shots)} shots...")
            image_results = image_gen.generate_batch(
                storyboard.shots,
                world_setting,
                global_style=storyboard.global_style
            )
            success_count = sum(1 for r in image_results if "error" not in r)
            click.echo(f"  ✓ Images generated: {success_count}/{len(storyboard.shots)}")

        # Generate audio (TTS)
        click.echo("  Generating audio...")
        audio_gen = AudioGenerator(
            project_id=project_id,
            output_dir=config.paths.projects_dir
        )
        audio_results = audio_gen.generate_batch(
            storyboard.shots,
            padding_before_ms=config.audio.padding_before_ms,
            padding_after_ms=config.audio.padding_after_ms
        )
        audio_count = sum(1 for r in audio_results if r.get("has_audio"))
        click.echo(f"  ✓ Audio generated: {audio_count} narration clips")

        # Add shot results to reporter
        for shot in storyboard.shots:
            img_result = next((r for r in image_results if r.get("shot_id") == shot.shot_id), {})
            reporter.add_shot_result(
                shot_id=shot.shot_id,
                shot_type=shot.shot_type.value,
                camera_movement=shot.camera_movement.value,
                description=shot.description or "",
                prompt=shot.visual_prompt,
                image_path=img_result.get("image_path"),
                success="error" not in img_result,
                error_msg=img_result.get("error", ""),
                seed=img_result.get("seed", 0),
                duration_seconds=img_result.get("duration_seconds", 0)
            )

        state.current_stage = "assets"
        state.completed_stages.append("assets")
        reporter.add_stage_result("assets", "success")
        checkpoint_mgr.save(project_id, state)

        # ========== Stage 3: Composition ==========
        click.echo("\n" + "="*50)
        click.echo("Stage 3: Timeline Composition")
        click.echo("="*50)
        reporter.add_stage_result("compose", "running")

        # Build timeline
        timeline_builder = TimelineBuilder(
            fps=config.video.fps,
            width=config.video.width,
            height=config.video.height
        )
        timeline = timeline_builder.build_from_assets(
            storyboard.shots,
            image_results,
            audio_results
        )
        click.echo(f"  ✓ Timeline built: {timeline.total_duration:.2f}s total")

        # Generate subtitles (ASS format for better CJK styling)
        subtitle_gen = SubtitleGenerator()
        subtitle_gen.generate_from_shots(storyboard.shots, audio_results)
        subtitle_gen.split_long_lines(max_chars=40)
        ass_path = project_dir / "subtitles.ass"
        subtitle_gen.export_ass(str(ass_path), style_name="Narration")
        click.echo(f"  ✓ Subtitles saved: {ass_path}")

        # Mix timeline
        mixer = Mixer(
            fps=config.video.fps,
            width=config.video.width,
            height=config.video.height
        )
        mixed_timeline = mixer.mix(timeline)

        # Export project file
        project_file = project_dir / "timeline.json"
        mixer.export_project_file(mixed_timeline, str(project_file))
        click.echo(f"  ✓ Timeline saved: {project_file}")

        state.current_stage = "compose"
        state.completed_stages.append("compose")
        reporter.add_stage_result("compose", "success")
        checkpoint_mgr.save(project_id, state)

        # ========== Stage 4: Render ==========
        click.echo("\n" + "="*50)
        click.echo("Stage 4: Video Rendering")
        click.echo("="*50)
        reporter.add_stage_result("render", "running")

        # Check if we have any images to render
        has_images = any(r.get("image_path") for r in image_results)
        if not has_images:
            click.echo("  ⚠ No images available, skipping render")
            click.echo("    Please ensure ComfyUI is running and retry")
            reporter.add_stage_result("render", "skipped")
        else:
            output_video = project_dir / "output" / "final.mp4"
            output_video.parent.mkdir(parents=True, exist_ok=True)

            encoder = VideoEncoder(
                fps=config.video.fps,
                codec="libx264",
                preset="medium"
            )
            click.echo(f"  Rendering video...")
            encoder.render(
                mixed_timeline,
                str(output_video),
                subtitle_path=str(ass_path)
            )
            click.echo(f"  ✓ Video rendered: {output_video}")
            reporter.add_stage_result("render", "success")

        state.current_stage = "render"
        state.completed_stages.append("render")
        checkpoint_mgr.save(project_id, state)

        # ========== Finalize ==========
        click.echo("\n" + "="*50)
        click.echo("Pipeline Complete!")
        click.echo("="*50)

        # Generate debug report
        report_path = reporter.finalize()
        click.echo(f"\n✓ Debug report: {report_path}")
        click.echo(f"✓ Project directory: {project_dir}")
        if has_images:
            click.echo(f"✓ Output video: {project_dir}/output/final.mp4")

    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        reporter.add_stage_result(state.current_stage or "unknown", "failed", message=str(e))
        reporter.finalize()
        click.echo(f"\n✗ Pipeline failed: {e}")
        click.echo(f"  Check debug report: {project_dir}/report.html")
        raise click.Abort()


if __name__ == "__main__":
    cli()
