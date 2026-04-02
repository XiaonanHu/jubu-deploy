"""
JSON Parser for KidsChat.

This module provides utilities for parsing JSON responses from language models,
with robust error handling and fallback mechanisms.
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple, TypeVar, Union, cast

from infrastructure.logging import get_logger
from jubu_chat.chat.common.types import TurnResponse
from jubu_chat.chat.models.base_model import GenerationTask, Message, ModelResponse

logger = get_logger(__name__)

T = TypeVar("T")


class JSONParser:
    """
    Parser for extracting structured data from language model responses.

    Features:
    - Robust extraction of JSON from text that may contain other content
    - Fallback mechanisms for handling malformed JSON
    - Type validation for extracted data
    """

    @staticmethod
    def extract_json(text: str) -> Optional[str]:
        """
        Extract JSON string from text that may contain other content.

        Tries patterns in priority order:
        1. JSON inside ```json ... ``` code blocks (most explicit)
        2. JSON inside generic ``` ... ``` code blocks
        3. Bare JSON array (checked before objects to avoid greedy {} matching inside arrays)
        4. Bare JSON object

        For bare JSON patterns, validates that the match is parseable JSON
        to avoid returning invalid substrings (e.g. matching {…} inside [{…}, {…}]).

        Args:
            text: Text that may contain JSON

        Returns:
            Extracted JSON string or None if no JSON found
        """
        # Phase 1: Code block patterns (high confidence, return immediately)
        code_block_patterns = [
            r"```json\s*([\s\S]*?)\s*```",  # JSON in code blocks
            r"```([\s\S]*?)\s*```",  # Any code block (fallback)
        ]

        for pattern in code_block_patterns:
            matches = re.findall(pattern, text)
            if matches:
                return matches[0]

        # Phase 2: Bare JSON patterns — collect all matches from both object
        # and array patterns, validate with json.loads, and return the longest
        # valid match. This avoids both:
        #   - greedy {}-matching inside arrays like [{...}, {...}]
        #   - array-first matching inside objects like {"key": [1, 2]}
        bare_patterns = [
            r"\[[\s\S]*\]",  # Bare JSON array
            r"{[\s\S]*}",  # Bare JSON object
        ]

        valid_matches = []
        any_match = None
        for pattern in bare_patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                if any_match is None:
                    any_match = match
                try:
                    json.loads(match)
                    valid_matches.append(match)
                except (json.JSONDecodeError, ValueError):
                    continue

        if valid_matches:
            # Return the longest valid JSON match (most complete structure)
            return max(valid_matches, key=len)

        # Fallback: return any match even if not valid JSON (for repair downstream)
        if any_match is not None:
            return any_match

        # If no JSON-like patterns found, return None
        return None

    @staticmethod
    def parse_json(text: str) -> Optional[Union[Dict[str, Any], List[Any]]]:
        """
        Parse JSON from text, with robust error handling.

        Args:
            text: Text containing JSON

        Returns:
            Parsed JSON object or None if parsing fails
        """
        # First try to extract JSON if the text contains other content
        json_str = JSONParser.extract_json(text) or text

        # Try to parse the JSON
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON: {e}")

            # Try to fix common JSON errors
            fixed_json = JSONParser._attempt_json_repair(json_str)
            if fixed_json:
                try:
                    return json.loads(fixed_json)
                except json.JSONDecodeError:
                    logger.warning("Failed to parse JSON even after repair attempt")

            return None

    @staticmethod
    def _attempt_json_repair(json_str: str) -> Optional[str]:
        """
        Attempt to repair common JSON formatting errors.

        Args:
            json_str: Potentially malformed JSON string

        Returns:
            Repaired JSON string or None if repair failed
        """
        # Replace single quotes with double quotes
        json_str = json_str.replace("'", '"')

        # Fix unquoted keys
        json_str = re.sub(r"([{,])\s*([a-zA-Z0-9_]+)\s*:", r'\1"\2":', json_str)

        # Fix trailing commas
        json_str = re.sub(r",\s*([}\]])", r"\1", json_str)

        # Add missing quotes to string values
        # This is a simplified approach and may not catch all cases
        json_str = re.sub(r":\s*([a-zA-Z][a-zA-Z0-9_]*)\s*([,}])", r':"\1"\2', json_str)

        return json_str

    @staticmethod
    def get_field(
        data: Optional[Dict[str, Any]], field: str, default: T = None
    ) -> Union[Any, T]:
        """
        Safely get a field from a dictionary with a default value.

        Args:
            data: Dictionary to extract from
            field: Field name to extract
            default: Default value if field is missing

        Returns:
            Field value or default
        """
        if data is None:
            return default
        return data.get(field, default)

    @staticmethod
    def parse_model_response(text: str) -> TurnResponse:
        """
        Parse a model response to extract the structured turn data.

        Args:
            text: Raw model response text, expected to be a JSON string.

        Returns:
            A TurnResponse object.
        """
        # Try to parse as JSON first
        parsed = JSONParser.parse_json(text)

        if isinstance(parsed, dict):
            try:
                # Validate the dictionary against the TurnResponse schema
                return TurnResponse(**parsed)
            except Exception as e:
                logger.warning(
                    f"Failed to validate response against TurnResponse schema: {e}. Falling back."
                )

        # Fallback: treat the entire text as the system_response
        logger.warning(
            "Failed to parse model response as structured JSON, using raw text for system_response."
        )
        return TurnResponse(
            system_response=text, child_name=None, current_interaction=None
        )

    @staticmethod
    def parse_safety_evaluation(text: str) -> Tuple[bool, Dict[str, Any]]:
        """
        Parse a safety evaluation response.

        Supports the new tag-based schema:
          {is_safe, severity, tags[], concerns[], redact_turn}
        as well as the legacy schema:
          {is_safe, concerns[], severity}

        Args:
            text: Raw safety evaluation text (expected to be JSON).

        Returns:
            Tuple of (is_safe, safety_details). safety_details always contains
            keys: is_safe, severity, tags, concerns, redact_turn.
        """
        parsed = JSONParser.parse_json(text)

        if isinstance(parsed, dict):
            is_safe = cast(bool, JSONParser.get_field(parsed, "is_safe", True))
            concerns = cast(List[str], JSONParser.get_field(parsed, "concerns", []))
            severity = cast(
                str,
                JSONParser.get_field(parsed, "severity", "none" if is_safe else "low"),
            )
            tags = cast(List[str], JSONParser.get_field(parsed, "tags", []))
            redact_turn = cast(bool, JSONParser.get_field(parsed, "redact_turn", False))

            return is_safe, {
                "is_safe": is_safe,
                "severity": severity,
                "tags": tags,
                "concerns": concerns,
                "redact_turn": redact_turn,
            }

        # Fallback: simple keyword-based safety check
        logger.warning("Failed to parse safety evaluation as JSON, using keyword check")
        unsafe_keywords = [
            "unsafe",
            "inappropriate",
            "harmful",
            "offensive",
            "personal information",
        ]
        is_safe = not any(keyword in text.lower() for keyword in unsafe_keywords)

        return is_safe, {
            "is_safe": is_safe,
            "severity": "medium" if not is_safe else "none",
            "tags": [],
            "concerns": ["Potential safety concern detected"] if not is_safe else [],
            "redact_turn": False,
            "parsing_error": True,
        }

    @staticmethod
    def parse_facts(text: str) -> List[Dict[str, Any]]:
        """
        Parse extracted facts from model response.

        Args:
            text: Raw facts extraction text

        Returns:
            List of fact dictionaries
        """
        # Try to parse as JSON
        parsed = JSONParser.parse_json(text)

        if isinstance(parsed, list):
            # Validate each fact has required fields
            facts = []
            for item in parsed:
                if isinstance(item, dict) and "content" in item:
                    # Ensure confidence is a float between 0 and 1
                    confidence = float(item.get("confidence", 0.5))
                    confidence = max(0.0, min(1.0, confidence))

                    facts.append({"content": item["content"], "confidence": confidence})
            return facts

        # Fallback: extract potential facts using simple heuristics
        logger.warning("Failed to parse facts as JSON, using text extraction")

        # Look for patterns like "Child likes X" or "Child is X years old"
        fact_patterns = [
            r"Child (?:likes|enjoys|loves|prefers) ([^\.]+)",
            r"Child is ([^\.]+)",
            r"Child has ([^\.]+)",
            r"Child wants ([^\.]+)",
            r"Child mentioned ([^\.]+)",
        ]

        facts = []
        for pattern in fact_patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                facts.append(
                    {
                        "content": f"Child {pattern.split(' ')[1]} {match}",
                        "confidence": 0.6,
                    }
                )

        return facts or [{"content": "No clear facts extracted", "confidence": 0.1}]

    @staticmethod
    def parse_interaction_analysis(text: str) -> Dict[str, Any]:
        """
        Parse interaction-specific analysis from model response.

        This method handles different formats based on the interaction type:
        - ChitChat: topics and sentiment
        - PretendPlay: imagination_elements and topics
        - Edutainment: educational_topics, knowledge_demonstrated, and question_asked

        Args:
            text: Raw interaction analysis text

        Returns:
            Dictionary with interaction-specific analysis data
        """
        # Try to parse as JSON
        parsed = JSONParser.parse_json(text)

        if isinstance(parsed, dict):
            # Initialize result with empty values for all possible fields
            result = {
                # ChitChat fields
                "topics": [],
                "sentiment": None,
                # PretendPlay fields
                "imagination_elements": [],
                # Edutainment fields
                "educational_topics": [],
                "knowledge_demonstrated": [],
                "question_asked": None,
            }

            # Update with values from parsed JSON
            for key, value in parsed.items():
                if key in result:
                    result[key] = value

            return result

        # Fallback: extract potential information using simple heuristics
        logger.warning(
            "Failed to parse interaction analysis as JSON, using text extraction"
        )

        result = {
            "topics": [],
            "sentiment": None,
            "imagination_elements": [],
            "educational_topics": [],
            "knowledge_demonstrated": [],
            "question_asked": None,
        }

        # Extract topics
        topic_match = re.search(r"topics:?\s*\[([^\]]+)\]", text, re.IGNORECASE)
        if topic_match:
            topics_text = topic_match.group(1)
            topics = [t.strip().strip("\"'") for t in topics_text.split(",")]
            result["topics"] = [t for t in topics if t]

        # Extract sentiment
        sentiment_match = re.search(
            r"sentiment:?\s*[\"']?(\w+)[\"']?", text, re.IGNORECASE
        )
        if sentiment_match:
            result["sentiment"] = sentiment_match.group(1).lower()

        # Extract imagination elements
        elements_match = re.search(
            r"imagination_elements:?\s*\[([^\]]+)\]", text, re.IGNORECASE
        )
        if elements_match:
            elements_text = elements_match.group(1)
            elements = [e.strip().strip("\"'") for e in elements_text.split(",")]
            result["imagination_elements"] = [e for e in elements if e]

        # Extract educational topics
        edu_topics_match = re.search(
            r"educational_topics:?\s*\[([^\]]+)\]", text, re.IGNORECASE
        )
        if edu_topics_match:
            edu_topics_text = edu_topics_match.group(1)
            edu_topics = [t.strip().strip("\"'") for t in edu_topics_text.split(",")]
            result["educational_topics"] = [t for t in edu_topics if t]

        # Extract knowledge demonstrated
        knowledge_match = re.search(
            r"knowledge_demonstrated:?\s*\[([^\]]+)\]", text, re.IGNORECASE
        )
        if knowledge_match:
            knowledge_text = knowledge_match.group(1)
            knowledge = [k.strip().strip("\"'") for k in knowledge_text.split(",")]
            result["knowledge_demonstrated"] = [k for k in knowledge if k]

        # Extract question asked
        question_match = re.search(
            r"question_asked:?\s*[\"']([^\"']+)[\"']", text, re.IGNORECASE
        )
        if question_match:
            result["question_asked"] = question_match.group(1)

        return result

    def parse_response(self, response: ModelResponse) -> Any:
        """
        Parse a model response based on its task type.

        Args:
            response: The ModelResponse from the language model

        Returns:
            Parsed data appropriate for the task
        """
        task = response.task

        if task == GenerationTask.GENERATE.value:
            return self.parse_model_response(response.content)
        elif task == GenerationTask.SAFETY_EVALUATE.value:
            return self.parse_safety_evaluation(response.content)
        elif task == GenerationTask.FACTS_EXTRACT.value:
            return self.parse_facts(response.content)
        elif task == GenerationTask.INTERACTION_ANALYZE.value:
            return self.parse_interaction_analysis(response.content)
        else:
            logger.warning(f"Unknown task type: {task}, using default parsing")
            return self.parse_json(response.content)
