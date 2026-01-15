"""
Storyboard generation from text input.

Uses LLM to:
1. Parse input text/script
2. Generate world setting (characters, locations, props)
3. Create shot-by-shot storyboard with visual prompts
"""

import json
import re
from typing import Optional

from ..shared.logger import get_logger
from ..shared.config import get_config
from ..shared.models import WorldSetting, Storyboard, Shot, Character, Location
from ..shared.prompts import PromptManager
from ..shared.exceptions import LLMError
from .schema import validate_world_setting, validate_storyboard


logger = get_logger(__name__)


class ScriptGenerator:
    """
    Script to storyboard generator.

    Two-phase generation:
    1. World Setting: Extract characters, locations, props
    2. Storyboard: Generate shots with visual prompts

    Uses Jinja2 templates for prompts (hot-reloadable).
    """

    def __init__(self, prompt_dir: str = "src/script/prompts"):
        self.config = get_config()
        self.prompts = PromptManager(prompt_dir)
        self._llm_client = None

    @property
    def llm_client(self):
        """Lazy-load LLM client"""
        if self._llm_client is None:
            self._llm_client = self._create_llm_client()
        return self._llm_client

    def _create_llm_client(self):
        """Create LLM client based on config"""
        provider = self.config.llm.provider

        if provider == "anthropic":
            try:
                import anthropic
                return anthropic.Anthropic(api_key=self.config.llm.api_key)
            except ImportError:
                raise LLMError("anthropic package not installed")

        elif provider == "openai":
            try:
                import openai
                return openai.OpenAI(
                    api_key=self.config.llm.api_key,
                    base_url=self.config.llm.base_url
                )
            except ImportError:
                raise LLMError("openai package not installed")

        else:
            raise LLMError(f"Unsupported LLM provider: {provider}")

    def generate_world_setting(self, input_text: str) -> WorldSetting:
        """
        Generate world setting from input text.

        Extracts:
        - Characters with descriptions
        - Locations/scenes
        - Key props

        Args:
            input_text: Raw script or story text

        Returns:
            WorldSetting with extracted entities
        """
        prompt = self.prompts.render(
            "world_setting.jinja2",
            script_content=input_text
        )

        response = self._call_llm(prompt)
        data = self._parse_json_response(response)

        # Validate and create model
        validate_world_setting(data)
        return WorldSetting(**data)

    def generate_storyboard(
        self,
        input_text: str,
        world_setting: WorldSetting,
        global_style: Optional[str] = None
    ) -> Storyboard:
        """
        Generate storyboard from text and world setting.

        Creates shots with:
        - Shot type and camera movement
        - Scene description
        - Visual prompt for image generation
        - Duration estimate

        Args:
            input_text: Raw script or story text
            world_setting: Previously generated world setting
            global_style: Optional style to apply to all shots

        Returns:
            Storyboard with shot list
        """
        prompt = self.prompts.render(
            "storyboard.jinja2",
            script_content=input_text,
            world_setting=world_setting.model_dump(),
            global_style=global_style or ""
        )

        response = self._call_llm(prompt)
        data = self._parse_json_response(response)

        # Validate
        validate_storyboard(data)

        # Create shots
        shots = [Shot(**shot_data) for shot_data in data.get("shots", [])]

        return Storyboard(
            title=data.get("title", "Untitled"),
            shots=shots,
            world_setting=world_setting,
            global_style=global_style
        )

    def enhance_visual_prompt(
        self,
        shot: Shot,
        world_setting: WorldSetting,
        global_style: Optional[str] = None
    ) -> str:
        """
        Generate enhanced visual prompt for a shot.

        Combines:
        - Shot description
        - Character references
        - Location details
        - Global style
        - Technical parameters (shot type, camera)

        Args:
            shot: Shot to enhance
            world_setting: World setting for reference
            global_style: Optional global style

        Returns:
            Enhanced visual prompt string
        """
        # Get character details
        characters = []
        for char_id in shot.characters:
            char = world_setting.get_character(char_id)
            if char:
                characters.append(char.model_dump())

        # Get location details
        location = None
        if shot.location_id:
            loc = world_setting.get_location(shot.location_id)
            if loc:
                location = loc.model_dump()

        prompt = self.prompts.render(
            "visual_prompt.jinja2",
            shot=shot.model_dump(),
            characters=characters,
            location=location,
            global_style=global_style or ""
        )

        return prompt.strip()

    def _call_llm(self, prompt: str) -> str:
        """Call LLM and return response text"""
        provider = self.config.llm.provider

        try:
            if provider == "anthropic":
                response = self.llm_client.messages.create(
                    model=self.config.llm.model,
                    max_tokens=self.config.llm.max_tokens,
                    messages=[{"role": "user", "content": prompt}]
                )
                return response.content[0].text

            elif provider == "openai":
                response = self.llm_client.chat.completions.create(
                    model=self.config.llm.model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=self.config.llm.max_tokens,
                    temperature=self.config.llm.temperature
                )
                return response.choices[0].message.content

        except Exception as e:
            raise LLMError(f"LLM call failed: {e}")

    def _parse_json_response(self, response: str) -> dict:
        """Extract and parse JSON from LLM response."""
        extracted = self._extract_json_text(response)

        candidates: list[str] = []
        if extracted:
            candidates.append(extracted)

        brace_slice = self._slice_first_json_object(extracted or response)
        if brace_slice and brace_slice not in candidates:
            candidates.append(brace_slice)

        last_error: Optional[Exception] = None
        for candidate in candidates:
            try:
                return json.loads(candidate)
            except json.JSONDecodeError as e:
                last_error = e
                repaired = self._repair_common_json_issues(candidate)
                if repaired != candidate:
                    try:
                        return json.loads(repaired)
                    except json.JSONDecodeError as e2:
                        last_error = e2

        if last_error is None:
            last_error = ValueError("Empty response")

        logger.error(f"Failed to parse LLM response as JSON: {last_error}")
        logger.debug(f"Response was: {response[:500]}")

        fixed = self._attempt_llm_json_repair(response)
        if fixed is not None:
            return fixed

        raise LLMError(f"Invalid JSON in LLM response: {last_error}")

    def _extract_json_text(self, response: str) -> str:
        """Extract JSON text from an LLM response that may include markdown fences."""
        text = (response or "").strip()
        if not text:
            return ""

        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            if end != -1:
                return text[start:end].strip()
            return text[start:].strip()

        if "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            if end != -1:
                return text[start:end].strip()
            return text[start:].strip()

        return text

    def _slice_first_json_object(self, text: str) -> str:
        """
        Best-effort slice of the first JSON object/array in text.
        Intended for cases where the LLM adds extra prose.
        """
        if not text:
            return ""

        start_candidates = [i for i in (text.find("{"), text.find("[")) if i != -1]
        if not start_candidates:
            return ""
        start = min(start_candidates)

        end_obj = text.rfind("}")
        end_arr = text.rfind("]")
        end = max(end_obj, end_arr)
        if end == -1 or end <= start:
            return ""

        return text[start:end + 1].strip()

    def _repair_common_json_issues(self, text: str) -> str:
        """Repair a few common JSON mistakes produced by LLMs."""
        if not text:
            return text

        repaired = text

        # Normalize “smart quotes” to standard quotes.
        repaired = repaired.replace("“", "\"").replace("”", "\"")
        repaired = repaired.replace("‘", "'").replace("’", "'")

        # Remove trailing commas before closing braces/brackets.
        repaired = re.sub(r",\s*([}\]])", r"\1", repaired)

        return repaired

    def _attempt_llm_json_repair(self, response: str) -> Optional[dict]:
        """
        Ask the LLM to repair invalid JSON once.
        Returns parsed dict on success, None otherwise.
        """
        snippet = (response or "").strip()
        if not snippet:
            return None

        max_chars = 20000
        if len(snippet) > max_chars:
            snippet = snippet[:max_chars]

        repair_prompt = (
            "你将收到一段本应为 JSON 的文本，但它无法被标准 JSON 解析器解析。\n"
            "请只输出修复后的、严格合法的 JSON（不允许 Markdown 代码块，不要解释，不要额外文本）。\n"
            "要求：尽量保持原始字段与内容不变；如果发现明显缺失的括号/逗号请补齐。\n\n"
            "原始文本：\n"
            f"{snippet}"
        )

        try:
            fixed_response = self._call_llm(repair_prompt)
            extracted = self._extract_json_text(fixed_response)
            extracted = self._repair_common_json_issues(extracted)
            return json.loads(extracted)
        except Exception:
            return None
