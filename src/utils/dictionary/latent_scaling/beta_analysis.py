import time
import numpy as np
import torch as th
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
import datetime
from argparse import ArgumentParser
import scipy.stats
from src.utils.dictionary.utils import load_latent_df, push_latent_df
from src.utils.dictionary.latent_scaling.utils import load_betas
from loguru import logger


def make_beta_df(
    crosscoder: str,
    results_dir: Path,
    num_samples: int,
):
    betas_dir = results_dir / "closed_form_scalars"
    plots_dir = results_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)

    configs = {
        "normal": {
            model: {
                target: f"{model}_{target}"
                for target in [
                    "error",
                    "reconstruction",
                    "activation",
                    "activation_no_bias",
                ]
            }
            for model in ["base", "chat"]
        },
    }

    df = load_latent_df(crosscoder)
    all_betas = load_betas_results(
        betas_dir / "all_latents", configs, num_samples=num_samples
    )
    df = add_possible_cols(df, df.index.tolist(), all_betas)

    if Path(betas_dir / "effective_chat_only_latents" / "indices.pt").exists():
        chat_specific_indices = th.load(
            betas_dir / "effective_chat_only_latents" / "indices.pt"
        ).tolist()
        chat_error_betas = load_betas_results(
            betas_dir / "effective_chat_only_latents",
            configs,
            num_samples=num_samples,
        )
        df = add_possible_cols(df, chat_specific_indices, chat_error_betas)
    if Path(betas_dir / "shared_baseline_latents" / "indices.pt").exists():
        shared_indices = th.load(
            betas_dir / "shared_baseline_latents" / "indices.pt"
        ).tolist()
        shared_error_betas = load_betas_results(
            betas_dir / "shared_baseline_latents",
            configs,
            num_samples=num_samples,
        )
        df = add_possible_cols(df, shared_indices, shared_error_betas)
    return df


def make_betas_plots(
    df: pd.DataFrame,
    chat_specific_indices: list[int],
    shared_indices: list[int],
    plots_dir: Path,
):
    target_df = df.iloc[chat_specific_indices]
    baseline_df = df.iloc[shared_indices]
    plot_error_vs_reconstruction(target_df, baseline_df, plots_dir, variant="standard")
    plot_error_vs_reconstruction(
        target_df, baseline_df, plots_dir, variant="custom_color"
    )
    plot_error_vs_reconstruction(target_df, baseline_df, plots_dir, variant="poster")

    plot_ratio_histogram(target_df, baseline_df, plots_dir, ratio_type="error")
    plot_ratio_histogram(target_df, baseline_df, plots_dir, ratio_type="reconstruction")

    plot_beta_distribution_histograms(target_df, plots_dir)
    plot_correlation_with_frequency(df, plots_dir)
    plot_rank_distributions(target_df, plots_dir)
    beta_ratio_error = df["beta_ratio_error"]
    beta_ratio_reconstruction = df["beta_ratio_reconstruction"]
    mask = ~np.isnan(beta_ratio_error) & ~np.isnan(beta_ratio_reconstruction)
    beta_ratio_error_clean = beta_ratio_error[mask]
    beta_ratio_reconstruction_clean = beta_ratio_reconstruction[mask]
    error_ranks = beta_ratio_error_clean.rank()
    reconstruction_ranks = beta_ratio_reconstruction_clean.rank()
    print(
        f"Beta ratio error ranks range: {error_ranks.min():.0f} to {error_ranks.max():.0f}"
    )
    print(
        f"Beta ratio reconstruction ranks range: {reconstruction_ranks.min():.0f} to {reconstruction_ranks.max():.0f}"
    )


def load_betas_results(
    base_path, configs, not_dead_mask=None, to_numpy=True, num_samples=None
):
    """
    Load beta values from result files.

    Args:
        base_path: Path to the base directory containing results
        configs: Dictionary configuration specifying which results to load
        not_dead_mask: Optional mask for filtering results
        to_numpy: Convert tensors to numpy arrays if True

    Returns:
        Tuple of (betas_out) dictionaries
    """
    if num_samples is None:
        num_samples = 50_000_000
    betas_out = {
        config: {
            model: {target: None for target in configs[config][model]}
            for model in configs[config]
        }
        for config in configs
    }
    for config in configs:
        for model in configs[config]:
            for target in configs[config][model]:
                try:
                    betas = load_betas(
                        base_path,
                        computation=configs[config][model][target],
                        num_samples=num_samples,
                    )
                except FileNotFoundError as e:
                    logger.debug(f"File not found: {e}. Skipping.")
                    continue

                betas = betas.cpu()
                if to_numpy:
                    betas = betas.numpy()
                if not_dead_mask is not None:
                    betas = betas[not_dead_mask]
                betas_out[config][model][target] = betas
    return betas_out


def add_col_to_df(df, indices, col, values):
    """Add column to dataframe with values at specified indices"""
    if col not in df.columns:
        df[col] = np.nan
    df.loc[indices, col] = values
    return df


def add_possible_cols(df, indices, betas):
    """Add beta columns to dataframe if they exist in the results"""
    if (
        betas["normal"]["base"]["error"] is not None
        and betas["normal"]["chat"]["error"] is not None
    ):
        print("Adding beta_error_base and beta_error_chat")
        df = add_col_to_df(
            df, indices, "beta_error_base", betas["normal"]["base"]["error"]
        )
        df = add_col_to_df(
            df, indices, "beta_error_chat", betas["normal"]["chat"]["error"]
        )
        df["beta_ratio_error"] = df["beta_error_base"] / df["beta_error_chat"]
    else:
        print("No beta_error_base or beta_error_chat found")
    if (
        betas["normal"]["base"]["reconstruction"] is not None
        and betas["normal"]["chat"]["reconstruction"] is not None
    ):
        df = add_col_to_df(
            df,
            indices,
            "beta_reconstruction_base",
            betas["normal"]["base"]["reconstruction"],
        )
        df = add_col_to_df(
            df,
            indices,
            "beta_reconstruction_chat",
            betas["normal"]["chat"]["reconstruction"],
        )
        df["beta_ratio_reconstruction"] = (
            df["beta_reconstruction_base"] / df["beta_reconstruction_chat"]
        )
    else:
        print("No beta_reconstruction_base or beta_reconstruction_chat found")

    if (
        betas["normal"]["base"]["activation"] is not None
        and betas["normal"]["chat"]["activation"] is not None
    ):
        df = add_col_to_df(
            df, indices, "beta_activation_base", betas["normal"]["base"]["activation"]
        )
        df = add_col_to_df(
            df, indices, "beta_activation_chat", betas["normal"]["chat"]["activation"]
        )
        df["beta_activation_ratio"] = (
            df["beta_activation_base"] / df["beta_activation_chat"]
        )
    else:
        print("No beta_activation_base or beta_activation_chat found")

    if (
        betas["normal"]["base"]["activation_no_bias"] is not None
        and betas["normal"]["chat"]["activation_no_bias"] is not None
    ):
        df = add_col_to_df(
            df,
            indices,
            "beta_activation_no_bias_base",
            betas["normal"]["base"]["activation_no_bias"],
        )
        df = add_col_to_df(
            df,
            indices,
            "beta_activation_no_bias_chat",
            betas["normal"]["chat"]["activation_no_bias"],
        )
        df["beta_activation_no_bias_ratio"] = (
            df["beta_activation_no_bias_base"] / df["beta_activation_no_bias_chat"]
        )
    else:
        print("No beta_activation_no_bias_base or beta_activation_no_bias_chat found")

    return df


def plot_beta_ratios_template_perc(target_df, filtered_df, plots_dir):
    """Plot histograms of beta ratios for template percentage

    Args:
        target_df: DataFrame containing all chat-only latents
        filtered_df: DataFrame containing latents with high template percentage
        plots_dir: Directory to save plots
    """
    if (
        "lmsys_ctrl_%" in target_df.columns
        and "beta_ratio_error" in target_df.columns
        and "beta_ratio_reconstruction" in target_df.columns
    ):
        low, high = -0.1, 1.1

        plt.figure(figsize=(8, 4))
        plt.rcParams["text.usetex"] = True
        plt.rcParams.update({"font.size": 24})

        # First subplot for beta_ratio_error
        ax1 = plt.subplot(1, 2, 1)
        # Plot full distribution
        target_df["beta_ratio_error"].hist(
            bins=50,
            range=(low, high),
            alpha=0.5,
            color="gray",
            label="All chat-only latents",
        )
        # Plot filtered distribution on top
        filtered_df["beta_ratio_error"].hist(
            bins=50,
            range=(low, high),
            alpha=0.7,
            color="blue",
            label="High Template Perc.",
        )
        plt.xlabel("$\\nu^\\epsilon$")
        ax1.tick_params(axis="y", rotation=90)
        plt.ylabel("Count")

        # Second subplot for beta_ratio_reconstruction
        ax2 = plt.subplot(1, 2, 2, sharey=ax1)
        # Plot full distribution
        target_df["beta_ratio_reconstruction"].hist(
            bins=50, range=(low, high), alpha=0.5, color="gray"
        )
        # Plot filtered distribution on top
        filtered_df["beta_ratio_reconstruction"].hist(
            bins=50, range=(low, high), alpha=0.7, color="blue"
        )
        plt.xlabel("$\\nu^r$")
        plt.setp(ax2.get_yticklabels(), visible=False)
        # Single legend for both plots
        plt.figlegend(fontsize=18.5, loc="center right", bbox_to_anchor=(0.532, 0.8))

        plt.tight_layout()
        plt.savefig(plots_dir / "beta_ratios_template_perc.pdf", bbox_inches="tight")
        plt.close()


def plot_error_vs_reconstruction(target_df, baseline_df, plots_dir, variant="standard"):
    """Plot scatter plot of error vs reconstruction ratios"""
    if not (
        "beta_ratio_error" in target_df.columns
        and "beta_ratio_reconstruction" in target_df.columns
    ):
        return

    zoom = [0, 1.1] if variant != "zoomed" else [-0.1, 1.1]
    chat_only_color = (0, 0.6, 1) if variant == "custom_color" else None

    # Create figure with a main plot and two side histograms
    fig_size = (
        (6, 3.5)
        if variant == "standard"
        else (4, 3) if variant == "custom_color" else (8, 3)
    )
    fig = plt.figure(figsize=fig_size)

    # Create a grid of subplots
    gs = plt.GridSpec(
        2,
        2,
        width_ratios=[3, 1.3],
        height_ratios=[1, 3],
        left=0.1,
        right=0.85,
        bottom=0.1,
        top=0.9,
        wspace=0.03,
        hspace=0.05,
    )

    # Create the three axes
    ax_scatter = fig.add_subplot(gs[1, 0])  # Main plot
    ax_histx = fig.add_subplot(gs[0, 0], sharex=ax_scatter)  # x-axis histogram
    ax_histy = fig.add_subplot(gs[1, 1], sharey=ax_scatter)  # y-axis histogram

    plt.rcParams["text.usetex"] = True
    plt.rcParams.update({"font.size": 20})

    # Filter out nans and apply zoom
    error_ratio = target_df["beta_ratio_error"]
    reconstruction_ratio = target_df["beta_ratio_reconstruction"]
    valid_mask = ~(np.isnan(error_ratio) | np.isnan(reconstruction_ratio))
    error_ratio_valid = error_ratio[valid_mask]
    reconstruction_ratio_valid = reconstruction_ratio[valid_mask]

    error_ratio_shared = baseline_df["beta_ratio_error"]
    reconstruction_ratio_shared = baseline_df["beta_ratio_reconstruction"]
    valid_mask_shared = ~(
        np.isnan(error_ratio_shared) | np.isnan(reconstruction_ratio_shared)
    )
    error_ratio_shared_valid = error_ratio_shared[valid_mask_shared]
    reconstruction_ratio_shared_valid = reconstruction_ratio_shared[valid_mask_shared]

    # Apply zoom mask to both datasets
    zoom_mask = (
        (error_ratio_valid > zoom[0])
        & (error_ratio_valid < zoom[1])
        & (reconstruction_ratio_valid > zoom[0])
        & (reconstruction_ratio_valid < zoom[1])
    )
    error_ratio_zoomed = error_ratio_valid[zoom_mask]
    reconstruction_ratio_zoomed = reconstruction_ratio_valid[zoom_mask]

    zoom_mask_shared = (
        (error_ratio_shared_valid > zoom[0])
        & (error_ratio_shared_valid < zoom[1])
        & (reconstruction_ratio_shared_valid > zoom[0])
        & (reconstruction_ratio_shared_valid < zoom[1])
    )
    error_ratio_shared_zoomed = error_ratio_shared_valid[zoom_mask_shared]
    reconstruction_ratio_shared_zoomed = reconstruction_ratio_shared_valid[
        zoom_mask_shared
    ]

    # Plot the scatter plots
    scatter_kwargs = {"alpha": 0.2, "s": 5}
    if chat_only_color:
        ax_scatter.scatter(
            error_ratio_zoomed,
            reconstruction_ratio_zoomed,
            label="chat-only",
            color=chat_only_color,
            **scatter_kwargs,
        )
        ax_scatter.scatter(
            error_ratio_shared_zoomed,
            reconstruction_ratio_shared_zoomed,
            label="shared",
            color="C1",
            **scatter_kwargs,
        )
    else:
        ax_scatter.scatter(
            error_ratio_zoomed,
            reconstruction_ratio_zoomed,
            label="Chat-only",
            **scatter_kwargs,
        )
        ax_scatter.scatter(
            error_ratio_shared_zoomed,
            reconstruction_ratio_shared_zoomed,
            label="Shared",
            **scatter_kwargs,
        )

    # Plot the histograms
    bins = 50
    hist_kwargs = {"bins": bins, "range": zoom, "alpha": 0.5}

    if chat_only_color:
        ax_histx.hist(
            error_ratio_zoomed, label="chat-only", color=chat_only_color, **hist_kwargs
        )
        ax_histx.hist(
            error_ratio_shared_zoomed, label="shared", color="C1", **hist_kwargs
        )
        ax_histy.hist(
            reconstruction_ratio_zoomed,
            orientation="horizontal",
            color=chat_only_color,
            **hist_kwargs,
        )
        ax_histy.hist(
            reconstruction_ratio_shared_zoomed,
            orientation="horizontal",
            color="C1",
            **hist_kwargs,
        )
    else:
        ax_histx.hist(error_ratio_zoomed, label="Chat-only", **hist_kwargs)
        ax_histx.hist(error_ratio_shared_zoomed, label="Shared", **hist_kwargs)
        ax_histy.hist(
            reconstruction_ratio_zoomed, orientation="horizontal", **hist_kwargs
        )
        ax_histy.hist(
            reconstruction_ratio_shared_zoomed, orientation="horizontal", **hist_kwargs
        )

    # Add grid to histograms
    ax_histx.grid(True, alpha=0.15)
    ax_histy.grid(True, alpha=0.15)
    ax_scatter.grid(True, alpha=0.15)

    # Turn off tick labels on histograms
    ax_histx.tick_params(labelbottom=False, bottom=False)
    ax_histy.tick_params(labelleft=False, left=False)

    # Add labels
    if variant == "poster":
        ax_scatter.set_ylabel(
            "$\\uparrow$ \n more \n Latent \n Decoupling ",
            labelpad=40,
            rotation=0,
            y=0.2,
        )
        ax_scatter.set_xlabel("more Complete Shrinkage $\\rightarrow$", labelpad=10)
    else:
        ax_scatter.set_xlabel("$\\nu^\\epsilon$")
        ax_scatter.set_ylabel("$\\nu^r$")

    # Add legend
    if variant == "custom_color":
        ax_histx.legend(
            fontsize=16,
            loc="upper right",
            handletextpad=0.2,
            bbox_to_anchor=(1.65, 1.2),
            handlelength=0.7,
            frameon=False,
        )
    else:
        ax_histx.legend(
            fontsize=16, markerscale=4, loc="lower right", bbox_to_anchor=(1.01, -3.2)
        )

    # Save figure
    suffix = (
        "_43" if variant == "custom_color" else "_poster" if variant == "poster" else ""
    )
    plt.savefig(
        plots_dir / f"error_vs_reconstruction_ratio_with_baseline{suffix}.pdf",
        bbox_inches="tight",
    )
    plt.close()


def plot_ratio_histogram(target_df, baseline_df, plots_dir, ratio_type="error"):
    """Plot histogram of beta ratio values for error or reconstruction"""
    if f"beta_ratio_{ratio_type}" not in target_df.columns:
        return

    zoom = None
    neg_filter_col = f"beta_{ratio_type}_base"
    ratio_col = f"beta_ratio_{ratio_type}"

    neg_mask = target_df[neg_filter_col] >= 0
    baseline_neg_mask = baseline_df[neg_filter_col] >= 0
    ratio_values = target_df[ratio_col][neg_mask]
    ratio_values_shared = baseline_df[ratio_col][baseline_neg_mask]

    # Filter out nans
    ratio_filtered = ratio_values[~np.isnan(ratio_values)]
    ratio_shared_filtered = ratio_values_shared[~np.isnan(ratio_values_shared)]

    # Compute combined range for consistent bins
    all_data = np.concatenate([ratio_filtered, ratio_shared_filtered])
    min_val, max_val = np.min(all_data), np.max(all_data) if zoom is None else zoom
    bins = np.linspace(min_val, max_val, 100)

    plt.figure(figsize=(5, 3))
    plt.rcParams["text.usetex"] = True
    plt.hist(ratio_filtered, bins=bins, alpha=0.5, label="Chat-only")
    plt.hist(ratio_shared_filtered, bins=bins, alpha=0.5, label="Shared")

    label = "$\\nu^\\epsilon$" if ratio_type == "error" else "$\\nu^r$"
    plt.xlabel(label)
    plt.ylabel("Count")

    plt.rcParams.update({"font.size": 16})
    plt.rcParams.update({"legend.fontsize": 16})

    plt.legend()
    plt.tight_layout()
    plt.savefig(plots_dir / f"{ratio_type}_ratio.pdf", bbox_inches="tight")
    plt.close()


def plot_beta_distribution_histograms(target_df, plots_dir):
    """Plot histograms of beta distribution values"""
    for beta_type in ["error", "reconstruction"]:
        base_col = f"beta_{beta_type}_base"
        chat_col = f"beta_{beta_type}_chat"

        if chat_col in target_df.columns and base_col in target_df.columns:
            try:
                plt.figure(figsize=(10, 6))
                plt.rcParams["text.usetex"] = True
                plt.rcParams.update({"font.size": 16})

                if beta_type == "reconstruction":
                    zoom = [-100, 100]
                    # Apply zoom to focus on a specific range
                    chat_zoomed = target_df[chat_col].clip(zoom[0], zoom[1])
                    base_zoomed = target_df[base_col].clip(zoom[0], zoom[1])

                    # Plot zoomed histograms
                    plt.hist(
                        chat_zoomed,
                        bins=50,
                        alpha=0.7,
                        label=f"Chat (zoomed to {zoom})",
                        color="blue",
                        density=True,
                    )
                    plt.hist(
                        base_zoomed,
                        bins=50,
                        alpha=0.7,
                        label=f"Base (zoomed to {zoom})",
                        color="red",
                        density=True,
                    )

                    # Add a note about zooming
                    plt.text(
                        0.05,
                        0.95,
                        f"Values clipped to range {zoom}",
                        transform=plt.gca().transAxes,
                        fontsize=12,
                        verticalalignment="top",
                        bbox=dict(boxstyle="round", facecolor="white", alpha=0.7),
                    )
                else:
                    # Plot regular histograms
                    plt.hist(
                        target_df[chat_col],
                        bins=50,
                        alpha=0.7,
                        label=f"Beta {beta_type.capitalize()} Chat",
                        color="blue",
                        density=True,
                    )
                    plt.hist(
                        target_df[base_col],
                        bins=50,
                        alpha=0.7,
                        label=f"Beta {beta_type.capitalize()} Base",
                        color="red",
                        density=True,
                    )
            except Exception as e:
                print(f"Error plotting {beta_type}: {e}")
                continue

            # Add labels and title
            plt.xlabel(f"Beta {beta_type.capitalize()}")
            plt.ylabel("Density")
            plt.title(
                f"Distribution of Beta {beta_type.capitalize()}s for Chat and Base Activations"
            )
            plt.legend()
            plt.grid(alpha=0.3)
            plt.tight_layout()
            plt.savefig(
                plots_dir / f"beta_{beta_type}_distribution_histogram.pdf",
                bbox_inches="tight",
            )
            plt.close()


def plot_correlation_with_frequency(df, plots_dir):
    """Plot correlation between frequency and beta ratios"""
    if (
        ("freq" in df.columns or "freq_val" in df.columns)
        and "beta_ratio_error" in df.columns
        and "beta_ratio_reconstruction" in df.columns
    ):
        import scipy.stats

        freq = df["freq"] if "freq" in df.columns else df["freq_val"]
        beta_ratio_error = df["beta_ratio_error"]
        beta_ratio_reconstruction = df["beta_ratio_reconstruction"]

        # Remove NaN values
        mask = (
            ~np.isnan(beta_ratio_error)
            & ~np.isnan(beta_ratio_reconstruction)
            & ~np.isnan(freq)
        )
        beta_ratio_error_clean = beta_ratio_error[mask]
        beta_ratio_reconstruction_clean = beta_ratio_reconstruction[mask]
        freq_clean = freq[mask]

        # Compute correlations
        corr_error, p_error = scipy.stats.pearsonr(beta_ratio_error_clean, freq_clean)
        corr_recon, p_recon = scipy.stats.pearsonr(
            beta_ratio_reconstruction_clean, freq_clean
        )

        print(
            f"Correlation between beta_ratio_error and frequency: {corr_error:.3f} (p={p_error:.3e})"
        )
        print(
            f"Correlation between beta_ratio_reconstruction and frequency: {corr_recon:.3f} (p={p_recon:.3e})"
        )

        # Plot scatter for error ratio
        plt.figure(figsize=(8, 4))
        plt.rcParams["text.usetex"] = True
        plt.rcParams.update({"font.size": 16})
        plt.scatter(freq_clean, beta_ratio_error_clean, alpha=0.5)
        plt.xlabel("Frequency")
        plt.ylabel("$\\nu^\\epsilon$ (beta ratio error)")
        plt.text(
            0.05,
            0.95,
            f"Correlation: {corr_error:.3f}\np={p_error:.2e}",
            transform=plt.gca().transAxes,
            verticalalignment="top",
        )
        plt.tight_layout()
        plt.savefig(plots_dir / "freq_vs_beta_ratio_error.pdf", bbox_inches="tight")
        plt.close()

        # Plot scatter for reconstruction ratio
        plt.figure(figsize=(8, 4))
        plt.rcParams["text.usetex"] = True
        plt.rcParams.update({"font.size": 16})
        plt.scatter(freq_clean, beta_ratio_reconstruction_clean, alpha=0.5)
        plt.xlabel("Frequency")
        plt.ylabel("$\\nu^r$ (beta ratio reconstruction)")
        plt.text(
            0.05,
            0.95,
            f"Correlation: {corr_recon:.3f}\np={p_recon:.2e}",
            transform=plt.gca().transAxes,
            verticalalignment="top",
        )
        plt.tight_layout()
        plt.savefig(
            plots_dir / "freq_vs_beta_ratio_reconstruction.pdf", bbox_inches="tight"
        )
        plt.close()


def plot_rank_distributions(target_df, plots_dir):
    """Plot step function of latent rank distributions"""
    for ratio_type in ["error", "reconstruction"]:
        if (
            f"beta_ratio_{ratio_type}" in target_df.columns
            and "dec_norm_diff" in target_df.columns
        ):
            # Get ranks of low nu latents
            low_nu_indices = (
                target_df[f"beta_ratio_{ratio_type}"]
                .sort_values(ascending=True)
                .index[:100]
            )
            all_latent_ranks = target_df["dec_norm_diff"].rank()
            low_nu_ranks = all_latent_ranks[low_nu_indices].sort_values()

            # Calculate fractions
            total_low_nu_latents = len(low_nu_indices)
            fractions = np.arange(1, len(low_nu_ranks) + 1) / total_low_nu_latents

            # Create figure
            plt.figure(figsize=(8, 5))
            plt.rcParams["text.usetex"] = True
            plt.rcParams.update({"font.size": 16})

            # Plot step function
            ratio_str = "$\\nu^\\epsilon$" if ratio_type == "error" else "$\\nu^r$"
            plt.step(
                low_nu_ranks,
                fractions,
                where="post",
                label=f"Fraction of low {ratio_str} latents",
            )

            # Update layout
            plt.xlabel("Rank in chat-only latent set")
            plt.ylabel(f"Fraction of 100 lowest {ratio_str} latents")
            plt.legend(fontsize=20 if ratio_type == "error" else None)
            plt.tight_layout()
            plt.savefig(
                plots_dir / f"low_nu_{ratio_type}_latents_rank_distribution.pdf",
                bbox_inches="tight",
            )
            plt.close()
