"""
Debug Reporter module.

Generates report.html to visualize pipeline execution,
showing prompts, generated images, and errors for debugging.
"""

import os
import json
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field


@dataclass
class ShotResult:
    """Result of a single shot generation"""
    shot_id: int
    shot_type: str
    camera_movement: str
    description: str
    prompt: str
    image_path: Optional[str] = None
    success: bool = True
    error_msg: str = ""
    seed: int = 0
    duration_seconds: float = 0.0
    metadata: dict = field(default_factory=dict)
    versions: list[str] = field(default_factory=list)  # All version paths


@dataclass
class StageResult:
    """Result of a pipeline stage"""
    stage: str
    status: str  # "success" | "failed" | "skipped"
    duration_seconds: float = 0.0
    message: str = ""


class DebugReporter:
    """
    Debug report generator.

    Creates an HTML report showing:
    - Pipeline execution progress
    - Each shot's prompt and generated image
    - Errors and warnings
    - Asset version history

    Usage:
        reporter = DebugReporter(project_id, output_dir)

        for shot in shots:
            result = generate_shot(shot)
            reporter.add_shot_result(result)

        reporter.finalize()
    """

    HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pipeline Debug Report - {project_id}</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            line-height: 1.6;
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        h1 {{ color: #333; border-bottom: 2px solid #4a90d9; padding-bottom: 10px; }}
        h2 {{ color: #555; margin-top: 30px; }}
        .header {{
            background: #fff;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .header-info {{ display: flex; gap: 30px; flex-wrap: wrap; }}
        .header-info div {{ }}
        .header-info label {{ font-weight: bold; color: #666; }}
        .stages {{
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            margin-bottom: 20px;
        }}
        .stage {{
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 14px;
        }}
        .stage.success {{ background: #d4edda; color: #155724; }}
        .stage.failed {{ background: #f8d7da; color: #721c24; }}
        .stage.pending {{ background: #e2e3e5; color: #383d41; }}
        .shot {{
            background: #fff;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            overflow: hidden;
        }}
        .shot-header {{
            background: #4a90d9;
            color: #fff;
            padding: 12px 20px;
            font-weight: bold;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .shot-header.error {{ background: #dc3545; }}
        .shot-body {{ padding: 20px; }}
        .shot-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }}
        @media (max-width: 800px) {{
            .shot-grid {{ grid-template-columns: 1fr; }}
        }}
        .section {{ margin-bottom: 15px; }}
        .section h4 {{
            margin: 0 0 8px 0;
            color: #666;
            font-size: 14px;
        }}
        .prompt {{
            background: #fffbe6;
            padding: 12px;
            border-radius: 4px;
            font-family: monospace;
            font-size: 13px;
            white-space: pre-wrap;
            word-break: break-word;
            border-left: 3px solid #ffc107;
        }}
        .description {{
            background: #e8f4fd;
            padding: 12px;
            border-radius: 4px;
            border-left: 3px solid #4a90d9;
        }}
        .image-container {{
            text-align: center;
        }}
        .image {{
            max-width: 100%;
            max-height: 400px;
            border-radius: 4px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.15);
        }}
        .status {{
            padding: 8px 12px;
            border-radius: 4px;
            font-size: 13px;
            margin-top: 10px;
        }}
        .status.success {{ background: #d4edda; color: #155724; }}
        .status.error {{ background: #f8d7da; color: #721c24; }}
        .metadata {{
            font-size: 12px;
            color: #666;
            margin-top: 10px;
        }}
        .versions {{
            margin-top: 15px;
            padding-top: 15px;
            border-top: 1px solid #eee;
        }}
        .versions h4 {{ margin-bottom: 10px; }}
        .version-list {{
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }}
        .version-thumb {{
            width: 80px;
            height: 80px;
            object-fit: cover;
            border-radius: 4px;
            cursor: pointer;
            border: 2px solid transparent;
            transition: border-color 0.2s;
        }}
        .version-thumb:hover {{ border-color: #4a90d9; }}
        .version-thumb.selected {{ border-color: #28a745; }}
        .summary {{
            background: #fff;
            padding: 20px;
            border-radius: 8px;
            margin-top: 30px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .summary-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 20px;
            text-align: center;
        }}
        .summary-item {{
            padding: 15px;
            background: #f8f9fa;
            border-radius: 8px;
        }}
        .summary-value {{
            font-size: 32px;
            font-weight: bold;
            color: #4a90d9;
        }}
        .summary-label {{ color: #666; font-size: 14px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Pipeline Debug Report</h1>
        <div class="header-info">
            <div><label>Project ID:</label> {project_id}</div>
            <div><label>Generated:</label> {timestamp}</div>
            <div><label>Total Shots:</label> {total_shots}</div>
        </div>
    </div>

    <h2>Pipeline Stages</h2>
    <div class="stages">
        {stages_html}
    </div>

    <h2>Shot Results</h2>
    {shots_html}

    <div class="summary">
        <h2>Summary</h2>
        <div class="summary-grid">
            <div class="summary-item">
                <div class="summary-value">{success_count}</div>
                <div class="summary-label">Successful</div>
            </div>
            <div class="summary-item">
                <div class="summary-value">{failed_count}</div>
                <div class="summary-label">Failed</div>
            </div>
            <div class="summary-item">
                <div class="summary-value">{total_duration:.1f}s</div>
                <div class="summary-label">Total Time</div>
            </div>
        </div>
    </div>

    <script>
        function selectVersion(shotId, version) {{
            // TODO: Implement version selection persistence
            console.log('Selected version', version, 'for shot', shotId);
        }}
    </script>
</body>
</html>'''

    SHOT_TEMPLATE = '''
    <div class="shot">
        <div class="shot-header {header_class}">
            <span>Shot #{shot_id} - {shot_type} - {camera_movement}</span>
            <span>{status_icon}</span>
        </div>
        <div class="shot-body">
            <div class="shot-grid">
                <div>
                    <div class="section">
                        <h4>📝 Description</h4>
                        <div class="description">{description}</div>
                    </div>
                    <div class="section">
                        <h4>🎨 Visual Prompt</h4>
                        <div class="prompt">{prompt}</div>
                    </div>
                    <div class="metadata">
                        Seed: {seed} | Duration: {duration:.2f}s
                    </div>
                </div>
                <div>
                    <div class="section">
                        <h4>🖼️ Generated Image</h4>
                        <div class="image-container">
                            {image_html}
                        </div>
                        <div class="status {status_class}">{status_msg}</div>
                    </div>
                    {versions_html}
                </div>
            </div>
        </div>
    </div>
    '''

    def __init__(self, project_id: str, output_dir: str):
        """
        Initialize debug reporter.

        Args:
            project_id: Project identifier
            output_dir: Directory to save report.html
        """
        self.project_id = project_id
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.report_path = self.output_dir / "report.html"

        self.shots: list[ShotResult] = []
        self.stages: list[StageResult] = []
        self.start_time = datetime.now()

    def add_stage_result(self, stage: str, status: str, duration: float = 0, message: str = ""):
        """Add a pipeline stage result"""
        self.stages.append(StageResult(
            stage=stage,
            status=status,
            duration_seconds=duration,
            message=message
        ))

    def add_shot_result(
        self,
        shot_id: int,
        shot_type: str,
        camera_movement: str,
        description: str,
        prompt: str,
        image_path: Optional[str] = None,
        success: bool = True,
        error_msg: str = "",
        seed: int = 0,
        duration_seconds: float = 0.0,
        metadata: dict = None,
        versions: list[str] = None
    ):
        """Add a shot generation result"""
        self.shots.append(ShotResult(
            shot_id=shot_id,
            shot_type=shot_type,
            camera_movement=camera_movement,
            description=description,
            prompt=prompt,
            image_path=image_path,
            success=success,
            error_msg=error_msg,
            seed=seed,
            duration_seconds=duration_seconds,
            metadata=metadata or {},
            versions=versions or []
        ))

    def _render_stages(self) -> str:
        """Render pipeline stages HTML"""
        html_parts = []
        for stage in self.stages:
            status_class = stage.status
            html_parts.append(
                f'<div class="stage {status_class}">{stage.stage}</div>'
            )
        return "".join(html_parts)

    def _render_shot(self, shot: ShotResult) -> str:
        """Render a single shot HTML"""
        # Image HTML
        if shot.image_path and Path(shot.image_path).exists():
            # Use relative path
            rel_path = os.path.relpath(shot.image_path, self.output_dir)
            image_html = f'<img class="image" src="{rel_path}" alt="Shot {shot.shot_id}">'
        elif shot.image_path:
            image_html = f'<img class="image" src="{shot.image_path}" alt="Shot {shot.shot_id}">'
        else:
            image_html = '<p style="color: #999;">No image generated</p>'

        # Status
        if shot.success:
            status_class = "success"
            status_msg = f"✅ Generated successfully"
            status_icon = "✓"
            header_class = ""
        else:
            status_class = "error"
            status_msg = f"❌ {shot.error_msg}"
            status_icon = "✗"
            header_class = "error"

        # Versions HTML
        if shot.versions:
            version_thumbs = []
            for i, v_path in enumerate(shot.versions):
                rel_path = os.path.relpath(v_path, self.output_dir) if Path(v_path).exists() else v_path
                selected = "selected" if v_path == shot.image_path else ""
                version_thumbs.append(
                    f'<img class="version-thumb {selected}" src="{rel_path}" '
                    f'onclick="selectVersion({shot.shot_id}, {i+1})" title="Version {i+1}">'
                )
            versions_html = f'''
            <div class="versions">
                <h4>📁 Version History ({len(shot.versions)})</h4>
                <div class="version-list">{"".join(version_thumbs)}</div>
            </div>
            '''
        else:
            versions_html = ""

        return self.SHOT_TEMPLATE.format(
            shot_id=shot.shot_id,
            shot_type=shot.shot_type,
            camera_movement=shot.camera_movement,
            description=shot.description or "(no description)",
            prompt=shot.prompt or "(no prompt)",
            image_html=image_html,
            status_class=status_class,
            status_msg=status_msg,
            status_icon=status_icon,
            header_class=header_class,
            seed=shot.seed,
            duration=shot.duration_seconds,
            versions_html=versions_html
        )

    def finalize(self) -> str:
        """Generate and save the final HTML report"""
        # Calculate summary
        success_count = sum(1 for s in self.shots if s.success)
        failed_count = len(self.shots) - success_count
        total_duration = sum(s.duration_seconds for s in self.shots)

        # Render shots
        shots_html = "".join(self._render_shot(shot) for shot in self.shots)

        # Render stages
        stages_html = self._render_stages()

        # Generate final HTML
        html = self.HTML_TEMPLATE.format(
            project_id=self.project_id,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            total_shots=len(self.shots),
            stages_html=stages_html,
            shots_html=shots_html,
            success_count=success_count,
            failed_count=failed_count,
            total_duration=total_duration
        )

        # Save
        self.report_path.write_text(html, encoding="utf-8")

        return str(self.report_path)

    def get_report_path(self) -> str:
        """Get the path to the generated report"""
        return str(self.report_path)
