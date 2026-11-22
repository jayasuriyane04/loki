"""Cross-encoder reranker (ONNX on CPU). Scores (query, passage) pairs jointly — much sharper than vector similarity."""

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)


class Reranker(ABC):
    name: str
    state: str = "loading"  # loading | ready | error | disabled
    error: str | None = None

    @abstractmethod
    async def load(self) -> None: ...

    @abstractmethod
    async def score(self, query: str, passages: list[str]) -> list[float]:
        """Relevance probability (0..1) for each passage."""


class OnnxCrossEncoder(Reranker):
    def __init__(self, model_dir: str, *, batch_size: int = 16, max_length: int = 512) -> None:
        self.dir = Path(model_dir)
        self.name = self.dir.name
        self.batch_size = batch_size
        self.max_length = max_length
        self._session = None
        self._tokenizer = None
        self._inputs: set[str] = set()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rerank")

    def _load_sync(self) -> None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        model = self.dir / "onnx" / "model.onnx"
        if not model.exists():
            raise FileNotFoundError(f"Reranker model not found at {model}")
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 4
        self._session = ort.InferenceSession(str(model), opts, providers=["CPUExecutionProvider"])
        self._inputs = {i.name for i in self._session.get_inputs()}
        tok = Tokenizer.from_file(str(self.dir / "tokenizer.json"))
        tok.enable_truncation(max_length=self.max_length)
        tok.enable_padding()
        self._tokenizer = tok
        self._score_sync("warm up", ["warm up"])

    async def load(self) -> None:
        start = time.perf_counter()
        try:
            await asyncio.get_running_loop().run_in_executor(self._pool, self._load_sync)
            self.state = "ready"
            log.info("reranker ready", extra={"model": self.name, "s": round(time.perf_counter() - start, 1)})
        except Exception as e:  # noqa: BLE001 - search falls back to hybrid ranking without it
            self.state, self.error = "error", str(e)[:300]
            log.error("reranker failed to load", extra={"error": self.error})

    def _score_sync(self, query: str, passages: list[str]) -> list[float]:
        assert self._session is not None and self._tokenizer is not None
        scores: list[float] = []
        for i in range(0, len(passages), self.batch_size):
            enc = self._tokenizer.encode_batch([(query, p) for p in passages[i : i + self.batch_size]])
            feed = {
                "input_ids": np.array([e.ids for e in enc], dtype=np.int64),
                "attention_mask": np.array([e.attention_mask for e in enc], dtype=np.int64),
            }
            if "token_type_ids" in self._inputs:
                feed["token_type_ids"] = np.array([e.type_ids for e in enc], dtype=np.int64)
            logits = self._session.run(None, feed)[0].reshape(-1)
            scores.extend((1 / (1 + np.exp(-logits))).tolist())
        return scores

    async def score(self, query: str, passages: list[str]) -> list[float]:
        if self.state != "ready":
            raise RuntimeError("reranker not ready")
        if not passages:
            return []
        return await asyncio.get_running_loop().run_in_executor(self._pool, self._score_sync, query, passages)
