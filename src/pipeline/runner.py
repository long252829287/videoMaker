"""
Pipeline runner module.

Orchestrates the video generation pipeline,
managing stage execution and error handling.
"""

import time
from enum import Enum
from typing import Callable, Optional
from dataclasses import dataclass, field

from ..shared.logger import get_logger
from ..shared.models import ProjectState, TaskResult
from ..shared.exceptions import PipelineError
from ..debug.reporter import DebugReporter
from .checkpoint import CheckpointManager


logger = get_logger(__name__)


class StageStatus(str, Enum):
    """Pipeline stage status"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StageResult:
    """Result of a pipeline stage execution"""
    stage: str
    status: StageStatus
    duration_seconds: float = 0.0
    error: Optional[str] = None
    outputs: dict = field(default_factory=dict)


class PipelineRunner:
    """
    Video generation pipeline runner.

    Manages sequential execution of pipeline stages:
    1. script - Generate storyboard from text
    2. character - Generate/prepare character assets
    3. assets - Generate images and audio
    4. compose - Combine assets into timeline
    5. render - Encode final video

    Features:
    - Checkpoint/resume support
    - Debug report generation
    - Serial execution (VRAM-safe for Phase 1)
    """

    STAGES = ["script", "character", "assets", "compose", "render"]

    def __init__(
        self,
        project_id: str,
        output_dir: str,
        checkpoint_dir: Optional[str] = None
    ):
        self.project_id = project_id
        self.output_dir = output_dir
        self.checkpoint_manager = CheckpointManager(
            checkpoint_dir or f"{output_dir}/checkpoints"
        )
        self.reporter = DebugReporter(project_id, output_dir)
        self.state = ProjectState(project_id=project_id)
        self._stage_handlers: dict[str, Callable] = {}

    def register_stage(self, stage: str, handler: Callable) -> None:
        """
        Register a handler function for a pipeline stage.

        Args:
            stage: Stage name (must be in STAGES)
            handler: Async function that executes the stage
        """
        if stage not in self.STAGES:
            raise ValueError(f"Invalid stage: {stage}. Must be one of {self.STAGES}")
        self._stage_handlers[stage] = handler

    def run(
        self,
        input_text: str,
        from_stage: Optional[str] = None,
        to_stage: Optional[str] = None
    ) -> TaskResult:
        """
        Run the pipeline.

        Args:
            input_text: Input text/script
            from_stage: Start from this stage (for resume)
            to_stage: Stop after this stage (for partial runs)

        Returns:
            TaskResult with pipeline outcome
        """
        start_time = time.time()

        # Determine stage range
        start_idx = self.STAGES.index(from_stage) if from_stage else 0
        end_idx = self.STAGES.index(to_stage) + 1 if to_stage else len(self.STAGES)
        stages_to_run = self.STAGES[start_idx:end_idx]

        logger.info(f"Running pipeline stages: {stages_to_run}")

        # Load checkpoint if resuming
        if from_stage:
            saved_state = self.checkpoint_manager.load(self.project_id)
            if saved_state:
                self.state = saved_state
                logger.info(f"Resumed from checkpoint: {from_stage}")

        # Initialize state
        self.state.input_text = input_text
        results: list[StageResult] = []

        try:
            for stage in stages_to_run:
                result = self._run_stage(stage)
                results.append(result)
                self.reporter.add_stage_result(
                    stage=stage,
                    status=result.status.value,
                    duration=result.duration_seconds,
                    message=result.error or ""
                )

                if result.status == StageStatus.FAILED:
                    raise PipelineError(
                        f"Stage '{stage}' failed: {result.error}",
                        stage=stage
                    )

                # Save checkpoint after each stage
                self.checkpoint_manager.save(self.project_id, self.state)

            # Finalize report
            report_path = self.reporter.finalize()
            logger.info(f"Debug report saved: {report_path}")

            return TaskResult(
                success=True,
                message=f"Pipeline completed successfully",
                data={
                    "stages": [r.stage for r in results],
                    "report_path": report_path,
                    "duration": time.time() - start_time
                }
            )

        except Exception as e:
            logger.error(f"Pipeline failed: {e}")
            self.reporter.finalize()

            return TaskResult(
                success=False,
                message=str(e),
                error_code="PIPELINE_FAILED"
            )

    def _run_stage(self, stage: str) -> StageResult:
        """Execute a single pipeline stage"""
        logger.info(f"Starting stage: {stage}")
        start_time = time.time()

        handler = self._stage_handlers.get(stage)
        if not handler:
            logger.warning(f"No handler registered for stage: {stage}")
            return StageResult(
                stage=stage,
                status=StageStatus.SKIPPED,
                duration_seconds=0.0
            )

        try:
            # Execute stage handler
            outputs = handler(self.state)
            duration = time.time() - start_time

            logger.info(f"Stage '{stage}' completed in {duration:.2f}s")

            return StageResult(
                stage=stage,
                status=StageStatus.COMPLETED,
                duration_seconds=duration,
                outputs=outputs or {}
            )

        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"Stage '{stage}' failed: {e}")

            return StageResult(
                stage=stage,
                status=StageStatus.FAILED,
                duration_seconds=duration,
                error=str(e)
            )

    def get_status(self) -> dict:
        """Get current pipeline status"""
        return {
            "project_id": self.project_id,
            "current_stage": self.state.current_stage,
            "completed_stages": self.state.completed_stages,
            "state": self.state.model_dump()
        }
