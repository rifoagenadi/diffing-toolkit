from dataclasses import dataclass
from typing import Dict, Tuple, List
from omegaconf import DictConfig
from loguru import logger
from hydra import initialize, compose
from pathlib import Path

HF_NAME = "science-of-finetuning"


@dataclass
class ModelConfig:
    """Configuration for a model (base or finetuned)."""

    name: str
    model_id: str
    attn_implementation: str = "eager"
    ignore_first_n_tokens_per_sample: int = 0
    token_level_replacement: dict = None
    text_column: str = "text"
    base_model_id: str = None
    dtype: str = "bfloat16"


@dataclass
class DatasetConfig:
    """Configuration for a dataset."""

    name: str
    id: str
    split: str
    is_chat: bool
    text_column: str = None
    messages_column: str = "messages"
    description: str = ""


def create_model_config(
    model_cfg: DictConfig, name_override: str = None
) -> ModelConfig:
    """Create a ModelConfig from configuration object."""
    return ModelConfig(
        name=name_override or model_cfg.name,
        model_id=model_cfg.model_id,
        attn_implementation=model_cfg.get("attn_implementation", "eager"),
        ignore_first_n_tokens_per_sample=model_cfg.get(
            "ignore_first_n_tokens_per_sample", 0
        ),
        token_level_replacement=model_cfg.get("token_level_replacement", None),
        text_column=model_cfg.get("text_column", "text"),
        base_model_id=model_cfg.get("base_model_id", None),
        dtype=model_cfg.get("dtype", "bfloat16"),
    )


def create_dataset_config(
    dataset_cfg: DictConfig, name: str, split: str
) -> DatasetConfig:
    """Create a DatasetConfig from configuration object for a specific split."""
    return DatasetConfig(
        name=name,
        id=dataset_cfg.id,
        split=split,
        is_chat=dataset_cfg.is_chat,
        text_column=dataset_cfg.get("text_column", None),
        messages_column=dataset_cfg.get("messages_column", "messages"),
        description=dataset_cfg.get("description", ""),
    )


def get_model_configurations(cfg: DictConfig) -> Tuple[ModelConfig, ModelConfig]:
    """Extract and prepare base and finetuned model configurations."""
    # Base model configuration
    base_model_cfg = create_model_config(cfg.model)

    # Finetuned model configuration - inherit from base model and override
    organism_cfg = cfg.organism
    finetuned_cfg = organism_cfg.finetuned_model

    # Create finetuned model config with inheritance
    finetuned_model_cfg = ModelConfig(
        name=finetuned_cfg.name,
        model_id=finetuned_cfg.model_id,
        base_model_id=finetuned_cfg.get("base_model_id", None),
        attn_implementation=finetuned_cfg.get(
            "attn_implementation", base_model_cfg.attn_implementation
        ),
        ignore_first_n_tokens_per_sample=finetuned_cfg.get(
            "ignore_first_n_tokens_per_sample",
            base_model_cfg.ignore_first_n_tokens_per_sample,
        ),
        token_level_replacement=finetuned_cfg.get(
            "token_level_replacement", base_model_cfg.token_level_replacement
        ),
        text_column=finetuned_cfg.get("text_column", base_model_cfg.text_column),
        dtype=finetuned_cfg.get("dtype", base_model_cfg.dtype),
    )

    # Apply organism-specific overrides
    organism_overrides = organism_cfg.get("preprocessing_overrides", {})
    if organism_overrides and "ignore_first_n_tokens_per_sample" in organism_overrides:
        finetuned_model_cfg.ignore_first_n_tokens_per_sample = organism_overrides[
            "ignore_first_n_tokens_per_sample"
        ]
        # Also apply to base model for consistency in organism context
        base_model_cfg.ignore_first_n_tokens_per_sample = organism_overrides[
            "ignore_first_n_tokens_per_sample"
        ]

    return base_model_cfg, finetuned_model_cfg


def get_dataset_configurations(
    cfg: DictConfig,
    use_chat_dataset: bool = True,
    use_pretraining_dataset: bool = True,
    use_training_dataset: bool = True,
) -> List[DatasetConfig]:
    """Extract and prepare all dataset configurations."""
    datasets = []

    # General datasets (used for all organisms)
    if hasattr(cfg, "chat_dataset") and use_chat_dataset:
        # Create one DatasetConfig for each split
        for split in cfg.chat_dataset.splits:
            datasets.append(
                create_dataset_config(
                    cfg.chat_dataset, cfg.chat_dataset.id.split("/")[-1], split
                )
            )

    if hasattr(cfg, "pretraining_dataset") and use_pretraining_dataset:
        # Create one DatasetConfig for each split
        for split in cfg.pretraining_dataset.splits:
            datasets.append(
                create_dataset_config(
                    cfg.pretraining_dataset,
                    cfg.pretraining_dataset.id.split("/")[-1],
                    split,
                )
            )

    # Organism-specific datasets
    organism_cfg = cfg.organism

    # Training dataset from finetuned model config (if present)
    if hasattr(organism_cfg, "training_dataset") and use_training_dataset:
        # Create one DatasetConfig for each split
        for split in organism_cfg.training_dataset.splits:
            datasets.append(
                create_dataset_config(
                    organism_cfg.training_dataset,
                    organism_cfg.training_dataset.id.split("/")[-1],
                    split,
                )
            )

    return datasets

def load_hydra_config(config_path: str, *overrides) -> DictConfig:
    """Load a Hydra config from a file."""
    with initialize(config_path=str(Path(config_path).parent), version_base=None):
        cfg = compose(config_name=Path(config_path).stem, overrides=overrides)
    return cfg
