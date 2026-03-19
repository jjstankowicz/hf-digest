"""Shared utilities for paper digest fetchers."""

EXTRACTED_FIELDS = ("category", "task", "key_results", "comments", "model_io", "hypotheses")
ARRAY_FIELDS = frozenset({"model_io", "hypotheses"})


def normalize_model_io(model_io: list[dict]) -> list[dict]:
    """Ensure inputs/outputs in each model_io entry are lists, not strings."""
    normalized = []
    for entry in model_io:
        normalized.append({
            "model": entry.get("model", ""),
            "inputs": (
                entry["inputs"] if isinstance(entry.get("inputs"), list)
                else [entry["inputs"]] if entry.get("inputs")
                else []
            ),
            "outputs": (
                entry["outputs"] if isinstance(entry.get("outputs"), list)
                else [entry["outputs"]] if entry.get("outputs")
                else []
            ),
        })
    return normalized
