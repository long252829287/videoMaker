"""
ComfyUI client module.

Provides:
- ComfyWorkflow: Workflow builder for manipulating ComfyUI JSON
- ComfyUIClient: API client with WebSocket task monitoring
"""

import json
import copy
import uuid
import time
from pathlib import Path
from typing import Any, Optional
from urllib.request import urlopen, Request
from urllib.error import URLError

try:
    import websocket
    HAS_WEBSOCKET = True
except ImportError:
    HAS_WEBSOCKET = False

from .logger import get_logger
from .exceptions import ComfyUIError, TimeoutError


logger = get_logger(__name__)


class ComfyWorkflow:
    """
    ComfyUI Workflow Builder.

    Provides a fluent interface for modifying ComfyUI workflow JSON,
    avoiding direct manipulation of node IDs.

    Example:
        workflow = (
            ComfyWorkflow("workflows/character_gen.json")
            .set_prompt("a young man with black hair")
            .set_seed(42)
            .set_lora("char_001.safetensors", 0.8)
            .apply_global_style("cinematic lighting, 8k")
            .build()
        )
    """

    def __init__(self, template_path: str):
        """
        Initialize workflow from template file.

        Args:
            template_path: Path to ComfyUI workflow JSON file
        """
        self.template_path = template_path
        self.template = self._load_template(template_path)
        self._node_map = self._build_node_map()

    def _load_template(self, path: str) -> dict:
        """Load workflow JSON from file"""
        template_file = Path(path)
        if not template_file.exists():
            raise FileNotFoundError(f"Workflow template not found: {path}")

        with open(template_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def _build_node_map(self) -> dict[str, str]:
        """
        Build a map of node class_type -> node_id.
        This allows referencing nodes by their type instead of ID.
        """
        node_map = {}
        for node_id, node_data in self.template.items():
            class_type = node_data.get("class_type", "")
            # Handle multiple nodes of the same type by appending _title
            title = node_data.get("_meta", {}).get("title", "")
            key = f"{class_type}_{title}" if title else class_type

            if key in node_map:
                # If duplicate, use class_type_id as key
                key = f"{class_type}_{node_id}"

            node_map[key] = node_id

        return node_map

    def _get_node_id(self, class_type: str) -> Optional[str]:
        """Get node ID by class type"""
        # Try exact match first
        if class_type in self._node_map:
            return self._node_map[class_type]

        # Try partial match
        for key, node_id in self._node_map.items():
            if class_type in key:
                return node_id

        return None

    def _set_node_input(self, class_type: str, input_name: str, value: Any) -> bool:
        """Set an input value for a node by class type"""
        node_id = self._get_node_id(class_type)
        if node_id is None:
            logger.warning(f"Node not found: {class_type}")
            return False

        if "inputs" not in self.template[node_id]:
            self.template[node_id]["inputs"] = {}

        self.template[node_id]["inputs"][input_name] = value
        return True

    def _get_node_input(self, class_type: str, input_name: str) -> Any:
        """Get an input value from a node"""
        node_id = self._get_node_id(class_type)
        if node_id is None:
            return None

        return self.template.get(node_id, {}).get("inputs", {}).get(input_name)

    def set_prompt(self, positive: str, negative: str = "") -> "ComfyWorkflow":
        """Set positive and negative prompts"""
        # Try common CLIP text encoder node names
        for cls in ["CLIPTextEncode", "CLIPTextEncodeSDXL"]:
            self._set_node_input(f"{cls}_positive", "text", positive)
            self._set_node_input(f"{cls}_negative", "text", negative or "")

        # Also try without suffix
        self._set_node_input("CLIPTextEncode", "text", positive)

        return self

    def set_seed(self, seed: int) -> "ComfyWorkflow":
        """Set random seed for KSampler"""
        for cls in ["KSampler", "KSamplerAdvanced"]:
            self._set_node_input(cls, "seed", seed)
        return self

    def set_image(self, image_path: str) -> "ComfyWorkflow":
        """Set input image for img2img or reference"""
        self._set_node_input("LoadImage", "image", image_path)
        return self

    def set_lora(self, lora_name: str, strength: float = 1.0) -> "ComfyWorkflow":
        """Load a LoRA model"""
        self._set_node_input("LoraLoader", "lora_name", lora_name)
        self._set_node_input("LoraLoader", "strength_model", strength)
        self._set_node_input("LoraLoader", "strength_clip", strength)
        return self

    def set_checkpoint(self, ckpt_name: str) -> "ComfyWorkflow":
        """Set the base checkpoint model"""
        self._set_node_input("CheckpointLoaderSimple", "ckpt_name", ckpt_name)
        return self

    def set_size(self, width: int, height: int) -> "ComfyWorkflow":
        """Set output image size"""
        self._set_node_input("EmptyLatentImage", "width", width)
        self._set_node_input("EmptyLatentImage", "height", height)
        return self

    def apply_global_style(self, style_prompt: str, style_lora: str = None) -> "ComfyWorkflow":
        """
        Apply global style to all prompts.
        This ensures visual consistency across all generated images.
        """
        # Append style to existing positive prompt
        for cls in ["CLIPTextEncode", "CLIPTextEncode_positive", "CLIPTextEncodeSDXL"]:
            current = self._get_node_input(cls, "text")
            if current:
                new_text = f"{current}, {style_prompt}"
                self._set_node_input(cls, "text", new_text)

        if style_lora:
            self.set_lora(style_lora, strength=0.6)

        return self

    def build(self) -> dict:
        """Build and return the final workflow JSON"""
        return copy.deepcopy(self.template)

    def save(self, output_path: str) -> None:
        """Save the modified workflow to a file"""
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(self.template, f, indent=2)


class ComfyUIClient:
    """
    ComfyUI API Client with WebSocket monitoring.

    Handles:
    - Submitting workflow prompts
    - Monitoring execution via WebSocket
    - Retrieving generated outputs
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8188):
        self.host = host
        self.port = port
        self.client_id = str(uuid.uuid4())
        self._http_url = f"http://{host}:{port}"
        self._ws_url = f"ws://{host}:{port}/ws"

    def is_available(self) -> bool:
        """Check if ComfyUI server is running"""
        try:
            response = urlopen(f"{self._http_url}/system_stats", timeout=5)
            return response.status == 200
        except (URLError, Exception):
            return False

    def submit_prompt(self, workflow: dict) -> str:
        """
        Submit a workflow prompt to ComfyUI.

        Args:
            workflow: ComfyUI workflow JSON

        Returns:
            prompt_id for tracking execution
        """
        payload = {
            "prompt": workflow,
            "client_id": self.client_id
        }

        req = Request(
            f"{self._http_url}/prompt",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        try:
            response = urlopen(req, timeout=30)
            result = json.loads(response.read())
            return result["prompt_id"]
        except URLError as e:
            raise ComfyUIError(f"Failed to submit prompt: {e}")

    def submit_and_wait(self, workflow: dict, timeout: float = 120.0) -> dict:
        """
        Submit a workflow and wait for completion.

        Args:
            workflow: ComfyUI workflow JSON
            timeout: Maximum wait time in seconds

        Returns:
            Output information including generated file paths
        """
        if not HAS_WEBSOCKET:
            raise ComfyUIError("websocket-client not installed. Run: pip install websocket-client")

        prompt_id = self.submit_prompt(workflow)
        logger.info(f"Submitted prompt: {prompt_id}")

        return self._wait_for_completion(prompt_id, timeout)

    def _wait_for_completion(self, prompt_id: str, timeout: float) -> dict:
        """Wait for prompt execution to complete via WebSocket"""
        ws_url = f"{self._ws_url}?clientId={self.client_id}"

        ws = websocket.create_connection(ws_url, timeout=timeout)
        logger.debug(f"Connected to WebSocket: {ws_url}")

        start_time = time.time()

        try:
            while True:
                if time.time() - start_time > timeout:
                    raise TimeoutError("ComfyUI execution", timeout)

                try:
                    msg_str = ws.recv()
                    msg = json.loads(msg_str)
                except websocket.WebSocketTimeoutException:
                    continue

                msg_type = msg.get("type")
                data = msg.get("data", {})

                if msg_type == "executing":
                    if data.get("node") is None and data.get("prompt_id") == prompt_id:
                        # Execution complete
                        logger.info(f"Prompt {prompt_id} completed")
                        break

                elif msg_type == "execution_error":
                    error_data = data.get("exception_message", "Unknown error")
                    raise ComfyUIError(f"Execution error: {error_data}", prompt_id)

                elif msg_type == "progress":
                    value = data.get("value", 0)
                    max_value = data.get("max", 100)
                    logger.debug(f"Progress: {value}/{max_value}")

            return self.get_history(prompt_id)

        finally:
            ws.close()

    def get_history(self, prompt_id: str) -> dict:
        """Get execution history and outputs for a prompt"""
        try:
            response = urlopen(f"{self._http_url}/history/{prompt_id}", timeout=30)
            history = json.loads(response.read())
            return history.get(prompt_id, {}).get("outputs", {})
        except URLError as e:
            raise ComfyUIError(f"Failed to get history: {e}", prompt_id)

    def get_image(self, filename: str, subfolder: str = "", folder_type: str = "output") -> bytes:
        """Download a generated image from ComfyUI"""
        params = f"filename={filename}&subfolder={subfolder}&type={folder_type}"
        url = f"{self._http_url}/view?{params}"

        try:
            response = urlopen(url, timeout=60)
            return response.read()
        except URLError as e:
            raise ComfyUIError(f"Failed to get image: {e}")

    def upload_image(self, image_path: str, subfolder: str = "") -> dict:
        """Upload an image to ComfyUI input folder"""
        import mimetypes
        from urllib.request import Request

        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        mime_type = mimetypes.guess_type(str(image_path))[0] or "image/png"

        # Build multipart form data
        boundary = uuid.uuid4().hex
        filename = image_path.name

        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
            f"Content-Type: {mime_type}\r\n\r\n"
        ).encode("utf-8")

        body += image_path.read_bytes()
        body += f"\r\n--{boundary}--\r\n".encode("utf-8")

        req = Request(
            f"{self._http_url}/upload/image",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST"
        )

        try:
            response = urlopen(req, timeout=60)
            return json.loads(response.read())
        except URLError as e:
            raise ComfyUIError(f"Failed to upload image: {e}")
