"""Local safetensors-only Qwen engine. Torch/Transformers are optional and lazy."""
from __future__ import annotations

from pathlib import Path
import threading

from .cpu_intent_prompt import SYSTEM_PROMPT, build_messages
from marsdog_voice_interaction.messages.intent_protocol import (
    SOCIAL_LABELS, INTENT_LABELS, CONTROL_LABELS, validate_intent_combination,
)

class InputRejected(ValueError):
    """Input must not be reinterpreted by a rule fallback after rejection."""


class ProtocolTrie:
    """Constrain syntax to the existing protocol; the model still selects semantics."""
    def __init__(self, tokenizer, eos_ids):
        self.root = {}
        self.eos_ids = [eos_ids] if isinstance(eos_ids, int) else list(eos_ids)
        for social in sorted(SOCIAL_LABELS):
            for intent in sorted(INTENT_LABELS):
                for control in sorted(CONTROL_LABELS):
                    if not validate_intent_combination(social, intent, control):
                        continue
                    node = self.root
                    for token in tokenizer.encode(f"{social}|{intent}|{control}", add_special_tokens=False):
                        node = node.setdefault(token, {})
                    node[None] = True

    def allowed(self, prefix):
        node = self.root
        for token in prefix:
            if token not in node:
                raise ValueError("Generated token prefix left the protocol grammar")
            node = node[token]
        return [token for token in node if token is not None] + (self.eos_ids if None in node else [])


class QwenCPUEngine:
    def __init__(self, model_path: str, *, num_threads: int = 2,
                 max_context_len: int = 4096, max_new_tokens: int = 32,
                 max_input_chars: int = 256, system_prompt: str = SYSTEM_PROMPT):
        self.path = Path(model_path).expanduser().resolve()
        if not self.path.is_dir():
            raise FileNotFoundError("A local Qwen model directory is required")
        for name in ("config.json", "model.safetensors", "tokenizer_config.json", "tokenizer.json"):
            if not (self.path / name).is_file():
                raise FileNotFoundError(self.path / name)
        if not 1 <= num_threads <= 16 or not 16 <= max_new_tokens <= 64:
            raise ValueError("Invalid CPU threads or generation token limit")
        if not 1024 <= max_context_len <= 8192 or not 1 <= max_input_chars <= 1024:
            raise ValueError("Invalid context or input limit")
        if not isinstance(system_prompt, str) or not system_prompt.strip():
            raise ValueError("A nonempty classifier prompt is required")
        self.max_context_len = max_context_len
        self.max_new_tokens = max_new_tokens
        self.max_input_chars = max_input_chars
        self.system_prompt = system_prompt
        self._lock = threading.Lock()
        self._cancelled = threading.Event()

        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, GenerationConfig
        torch.set_num_threads(num_threads)
        self._torch = torch
        self._tokenizer = AutoTokenizer.from_pretrained(
            str(self.path), local_files_only=True, trust_remote_code=False)
        self._model = AutoModelForCausalLM.from_pretrained(
            str(self.path), local_files_only=True, trust_remote_code=False,
            use_safetensors=True, dtype=torch.float32, attn_implementation="eager").to("cpu").eval()
        if self._model.config.model_type != "qwen2":
            raise ValueError("This development engine supports the supplied Qwen2 model only")
        self._generation = GenerationConfig(
            do_sample=False, max_new_tokens=max_new_tokens,
            bos_token_id=self._model.config.bos_token_id,
            eos_token_id=self._model.generation_config.eos_token_id,
            pad_token_id=self._tokenizer.pad_token_id,
            repetition_penalty=1.0, use_cache=True)
        self._grammar = ProtocolTrie(self._tokenizer, self._generation.eos_token_id)

    def classify(self, utterance: str) -> str:
        if not isinstance(utterance, str) or not utterance.strip():
            raise InputRejected("Empty utterance")
        if len(utterance) > self.max_input_chars:
            raise InputRejected("Input too long; refusing to truncate intent or negation")
        if "|" in utterance or any(marker in utterance for marker in ("<|im_", "<|endoftext|>")):
            raise InputRejected("Chat control tokens and literal protocol delimiters are not utterance data")
        from transformers import StoppingCriteria, StoppingCriteriaList
        cancelled = self._cancelled
        class Cancelled(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs):
                return cancelled.is_set()
        with self._lock:
            if self._model is None or cancelled.is_set():
                raise RuntimeError("Qwen CPU engine is stopped")
            text = self._tokenizer.apply_chat_template(
                build_messages(utterance.strip(), self.system_prompt),
                tokenize=False, add_generation_prompt=True)
            encoded = self._tokenizer(text, return_tensors="pt", add_special_tokens=False)
            length = encoded["input_ids"].shape[-1]
            if length + self.max_new_tokens > self.max_context_len:
                raise InputRejected("Prompt exceeds configured context; no implicit truncation")
            with self._torch.inference_mode():
                generated = self._model.generate(
                    **encoded, generation_config=self._generation,
                    prefix_allowed_tokens_fn=lambda batch_id, ids: self._grammar.allowed(ids[length:].tolist()),
                    stopping_criteria=StoppingCriteriaList([Cancelled()]))
            if cancelled.is_set():
                raise RuntimeError("Qwen CPU inference cancelled")
            return self._tokenizer.decode(generated[0, length:], skip_special_tokens=True).strip()

    def release(self):
        self._cancelled.set()
        with self._lock:
            self._model = None
            self._tokenizer = None
