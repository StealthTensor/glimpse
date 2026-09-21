"""
Biometric Vector Matcher module for Glimpse.
Computes cosine similarity and validates against enrolled template sets.
"""

from __future__ import annotations
import logging
from typing import List, Tuple
import numpy as np

logger = logging.getLogger("glimpse.engine.matcher")

class BiometricMatcher:
    """Matches candidate feature vectors against enrolled biometric templates."""

    def __init__(self, threshold: float = 0.55):
        self.threshold = threshold

    @staticmethod
    def cosine_similarity(v1: np.ndarray, v2: np.ndarray) -> float:
        """Compute cosine similarity between two feature vectors."""
        v1 = np.asarray(v1, dtype=np.float32).flatten()
        v2 = np.asarray(v2, dtype=np.float32).flatten()

        if len(v1) != len(v2):
            logger.warning(f"Vector dimension mismatch ({len(v1)} vs {len(v2)}). Re-enrollment needed.")
            return 0.0

        norm1 = np.linalg.norm(v1)
        norm2 = np.linalg.norm(v2)

        if norm1 < 1e-6 or norm2 < 1e-6:
            return 0.0

        return float(np.dot(v1, v2) / (norm1 * norm2))

    def match(self, candidate_vector: np.ndarray, enrolled_vectors: List[np.ndarray]) -> Tuple[bool, float]:
        """
        Compare candidate vector against list of enrolled template vectors.
        Returns: (is_match: bool, best_similarity: float)
        """
        if not enrolled_vectors:
            return False, 0.0

        best_score = -1.0
        for template in enrolled_vectors:
            score = self.cosine_similarity(candidate_vector, template)
            if score > best_score:
                best_score = score

        is_match = best_score >= self.threshold
        logger.debug(f"Matching candidate vs {len(enrolled_vectors)} templates: best={best_score:.4f}, thresh={self.threshold} -> match={is_match}")
        return is_match, best_score
