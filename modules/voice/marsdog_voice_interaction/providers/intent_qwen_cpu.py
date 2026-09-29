"""Optional prompted CPU intent provider; original RKLLM engine is independent."""
from __future__ import annotations
import logging
import threading
from typing import Any

from marsdog_voice_interaction.adapters.llm.cpu_intent_prompt import SYSTEM_PROMPT
from marsdog_voice_interaction.adapters.llm.qwen_cpu_engine import QwenCPUEngine, InputRejected
from marsdog_voice_interaction.messages.intent_protocol import classification_to_event, parse_intent_tag
from marsdog_voice_interaction.providers.base import BaseProvider

logger = logging.getLogger(__name__)

class IntentQwenCPUProvider(BaseProvider):
    # Generic instruction models need punctuation and word boundaries.
    preserve_asr_text = True
    background_intent = True

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self._engine = None
        self._parse_lock = threading.Lock()
        self.last_error = ""
        self.last_output = ""
        self.input_rejected = False

    def start(self):
        self.stop()
        self.last_error = ""
        try:
            self._engine = QwenCPUEngine(
                str(self.config.get("model", "")),
                num_threads=int(self.config.get("num_threads", 2)),
                max_context_len=int(self.config.get("max_context_len", 4096)),
                max_new_tokens=int(self.config.get("max_new_tokens", 32)),
                max_input_chars=int(self.config.get("max_input_chars", 256)),
                system_prompt=self.config.get("system_prompt", SYSTEM_PROMPT))
            self.available = True
        except Exception as exc:
            self._engine = None
            self.available = False
            self.last_error = str(exc)
            logger.warning("Qwen CPU intent unavailable: %s", exc)

    def stop(self):
        self.available = False
        engine, self._engine = self._engine, None
        if engine is not None:
            engine.release()

    def parse_intent(self, asr_text: str) -> dict[str, Any] | None:
        with self._parse_lock:
            self.last_error = self.last_output = ""
            self.input_rejected = False
            engine = self._engine
            if not self.available or engine is None:
                self.last_error = "unavailable"
                return None
            if not isinstance(asr_text, str) or not asr_text.strip():
                self.last_error = "empty_input"
                return None
            try:
                self.last_output = engine.classify(asr_text.strip())
                if not self.available or self._engine is not engine:
                    self.last_error = "stopped_during_inference"
                    return None
                parts = parse_intent_tag(self.last_output)
                if parts is None:
                    self.last_error = "invalid_protocol_output"
                    return None
                return classification_to_event(*parts, asr_text=asr_text.strip(),
                                               source="qwen_cpu", confidence=0.0)
            except InputRejected as exc:
                self.input_rejected = True
                self.last_error = str(exc)
                return None
            except Exception as exc:
                self.last_error = str(exc)
                logger.warning("Qwen CPU intent classification failed: %s", exc)
                return None
