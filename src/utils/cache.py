from dictionary_learning.cache import PairedActivationCache, ActivationCache
import torch as th
from pathlib import Path
from tqdm.auto import tqdm

class TokenCache:
    """
    A wrapper around an ActivationCache that provides access to a subset of tokens.

    This class enables efficient filtering and selection of tokens from an underlying
    activation cache without duplicating the entire cache. It maintains a mapping of indices
    that reference the original cache, allowing for memory-efficient operations on subsets
    of the data.

    Example:
        from utils.cache import TokenCache
        from utils.activations import load_activation_dataset

        cache = load_activation_dataset(
            activation_store_dir=DATA_ROOT / "activations/",
            split="validation",
            dataset_name="lmsys-chat-1m-chat-formatted",
            base_model="gemma-2-2b",
            finetuned_model="gemma-2-2b-it",
            layer=13,
        )
        token_cache = TokenCache(cache)
        print(token_cache[0])  # Access the first activation (token, activation)
        only_bos_token_cache = token_cache.select_tokens([2])
        print(only_bos_token_cache[0])  # Access the first bos activation (token, activation)
        no_bos_token_cache = token_cache.remove_tokens([2])
        print(no_bos_token_cache[0])  # Access the first bos activation (token, activation)

    Attributes:
        cache: The underlying ActivationCache or PairedActivationCache containing token data and activations.
        indices: List of indices into the original cache that this TokenCache provides access to.
        tokens: The subset of tokens from the original cache corresponding to the selected indices.
    """

    def __init__(
        self, cache: ActivationCache | PairedActivationCache, indices: list[int] = None
    ):
        """
        Initialize a TokenCache with a reference to an activation cache and optional indices.

        Args:
            cache: The underlying ActivationCache or PairedActivationCache to wrap.
            indices: Optional list of indices to include. If None, includes all indices from the original cache.

        Raises:
            ValueError: If the cache type is not supported.
            AssertionError: If using a PairedActivationCache with mismatched tokens.
        """
        self.cache = cache
        if indices is not None:
            assert len(indices) > 0, "Indices must be a non-empty list"
            self.indices = indices
        else:
            self.indices = list(range(len(cache)))

        if isinstance(cache, PairedActivationCache):
            assert th.all(
                cache.tokens[0] == cache.tokens[1]
            ), "Tokens must be the same for PairedActivationCache"
            self._tokens = cache.tokens[0]
        elif isinstance(cache, ActivationCache):
            self._tokens = cache.tokens
        else:
            raise ValueError(f"Unsupported cache type: {type(cache)}")

    @property
    def tokens(self):
        return self._tokens[self.indices]

    def __len__(self) -> int:
        """
        Return the number of tokens in this cache subset.

        Returns:
            int: The number of tokens in the current subset.
        """
        return len(self.indices)

    def __getitem__(self, index: int) -> tuple:
        """
        Retrieve a token and its activation at the specified index.

        Args:
            index: Index into this TokenCache's subset.

        Returns:
            tuple: A pair containing (token, activation) from the underlying cache.
        """
        full_cache_index = self.indices[index]
        return self._tokens[full_cache_index], self.cache[full_cache_index]

    def get_token(self, index: int) -> int:
        """
        Retrieve the token ID at the specified index without its activation.

        This method provides direct access to just the token ID, unlike __getitem__
        which returns both the token and its activation.

        Args:
            index: Index into this TokenCache's subset.

        Returns:
            int: The token ID from the underlying cache at the specified index.
        """
        full_cache_index = self.indices[index]
        return self._tokens[full_cache_index]

    def remove_tokens(self, token_ids: list[int]) -> "TokenCache":
        """
        Create a new TokenCache excluding the specified indices.

        This method filters out tokens at the specified indices from the current subset,
        returning a new TokenCache with the remaining tokens.

        Args:
            token_ids: List of token ids to exclude from the current subset.

        Returns:
            TokenCache: A new TokenCache instance with the filtered subset of tokens.
        """
        indices_to_exclude = set(token_ids)
        tokens = self._tokens.tolist()
        indices = [i for i in self.indices if tokens[i] not in indices_to_exclude]
        return TokenCache(self.cache, indices)

    def select_tokens(self, token_ids: list[int]) -> "TokenCache":
        """
        Create a new TokenCache including only the specified indices.

        This method creates a new subset containing only the tokens at the specified indices,
        allowing for precise selection of tokens of interest.

        Args:
            token_ids: List of token ids to include in the new subset.

        Returns:
            TokenCache: A new TokenCache instance with only the selected tokens.
        """
        indices_set = set(token_ids)
        tokens = self._tokens.tolist()
        indices = [i for i in self.indices if tokens[i] in indices_set]
        return TokenCache(self.cache, indices)


class SampleCache:
    """
    A cache that organizes activations by samples, where each sample starts with a BOS token.

    This class provides a way to access activations and tokens for complete sequences
    (samples) rather than individual tokens. It identifies sample boundaries using
    the beginning-of-sequence (BOS) token.

    Example:
        from utils.cache import SampleCache
        from utils.activations import load_activation_dataset

        cache = load_activation_dataset(
            activation_store_dir="$DATASTORE/activations/",
            split="validation",
            dataset_name="lmsys-chat-1m-chat-formatted",
            base_model="gemma-2-2b",
            finetuned_model="gemma-2-2b-it",
            layer=13,
        )
        sample_cache = SampleCache(cache, tokenizer.bos_token_id)

        sample_cache.sequences # List of sequences of tokens
        sample_cache[0] # (tokens: (len(sequence), ), activations: (len(sequence), num_layers, dim_model))

    Args:
        cache: An ActivationCache or PairedActivationCache containing the tokens and activations.
        bos_token_id: The token ID that marks the beginning of a sequence (default: 2).

    Raises:
        ValueError: If the cache type is not supported.
        AssertionError: If tokens don't match in a PairedActivationCache or if shuffled shards are used.
    """

    def __init__(
        self, cache: ActivationCache | PairedActivationCache, bos_token_id: int = 2
    ):
        self.cache = cache
        self.bos_token_id = bos_token_id

        if isinstance(cache, PairedActivationCache):
            assert th.all(
                cache.tokens[0] == cache.tokens[1]
            ), "Tokens must be the same for PairedActivationCache"
            self._tokens = cache.tokens[0]
            assert (
                not cache.activation_cache_1.config["shuffle_shards"]
                and not cache.activation_cache_2.config["shuffle_shards"]
            ), "Shuffled shards are not supported for SampleCache"
        elif isinstance(cache, ActivationCache):
            self._tokens = cache.tokens
            assert not cache.config[
                "shuffle_shards"
            ], "Shuffled shards are not supported for SampleCache"
        else:
            raise ValueError(f"Unsupported cache type: {type(cache)}")
        tokens = self._tokens.tolist()
        self.sample_start_indices = [
            i for i in range(len(tokens)) if tokens[i] == self.bos_token_id
        ] + [len(tokens)]

    def __len__(self):
        """
        Returns the number of samples in the cache.

        Returns:
            int: The number of distinct samples identified by BOS tokens.
        """
        return len(self.sample_start_indices) - 1

    @property
    def sequences(self):
        """
        Returns all token sequences in the cache.

        Returns:
            list: A list of token tensors, where each tensor represents a complete sequence.
        """
        return [
            self._tokens[start_index:end_index]
            for start_index, end_index in zip(
                self.sample_start_indices[:-1], self.sample_start_indices[1:]
            )
        ]

    def __getitem__(self, index: int):
        """
        Retrieves tokens and activations for a specific sample.

        Args:
            index: The index of the sample to retrieve.

        Returns:
            tuple: A pair containing:
                - The token sequence for the sample
                - A tensor of activations for each token in the sample
        """
        start_index = self.sample_start_indices[index]
        end_index = self.sample_start_indices[index + 1]
        sample_tokens = self._tokens[start_index:end_index]
        sample_activations = th.stack(
            [self.cache[i] for i in range(start_index, end_index)], dim=0
        )
        return sample_tokens, sample_activations