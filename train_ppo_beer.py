#!/usr/bin/env python3
"""Quick training entry-point for the Battleship PPO agent.

Usage (from repository root):

    python train_ppo_beer.py

Adjust the constants at the top for longer training or different settings.
"""

from pathlib import Path
import argparse
import json

from beer.ppo_bot import train, DEFAULT_MODEL_PATH, _GridCNN


def main() -> None:
    parser = argparse.ArgumentParser("Flexible PPO Battleship trainer")

    parser.add_argument("--timesteps", type=int, default=2_000_000, help="Total PPO timesteps")
    parser.add_argument("--envs", type=int, default=8, help="Parallel environments (processes)")
    parser.add_argument("--no-mask", action="store_true", help="Disable action masking")
    parser.add_argument("--small-cnn", action="store_true", help="Use compact CNN feature extractor (_GridCNN)")
    parser.add_argument("--out", default=str(DEFAULT_MODEL_PATH), help="Model output path (.zip)")
    parser.add_argument("--stop-shots", type=int, help="Early-stop when mean shots ≤ N")
    parser.add_argument("--eval-freq", type=int, default=200_000, help="Timesteps between evals")
    parser.add_argument("--eval-episodes", type=int, default=30, help="Episodes per eval run")
    parser.add_argument("--ppo-kwargs", type=str, help="JSON dict with extra PPO kwargs (e.g. '{\"learning_rate\":1e-4}')")

    args = parser.parse_args()

    masked = not args.no_mask

    # Parse extra PPO keyword arguments
    extra_kwargs = {}
    if args.ppo_kwargs:
        try:
            extra_kwargs = json.loads(args.ppo_kwargs)
        except json.JSONDecodeError as exc:
            parser.error(f"--ppo-kwargs must be valid JSON: {exc}")

    # Plug in the custom CNN if requested
    if args.small_cnn:
        # SB3 expects custom extractors inside policy_kwargs
        extra_kwargs.setdefault("policy", "CnnPolicy")
        pk = extra_kwargs.setdefault("policy_kwargs", {})
        pk["features_extractor_class"] = _GridCNN

    print(
        f"[train_ppo_beer] Starting training: timesteps={args.timesteps:,}, "
        f"envs={args.envs}, masked={masked}, out={args.out}"
    )

    train(
        total_timesteps=args.timesteps,
        n_envs=args.envs,
        masked=masked,
        model_path=Path(args.out),
        stop_mean_shots=args.stop_shots,
        eval_freq=args.eval_freq,
        eval_episodes=args.eval_episodes,
        **extra_kwargs,
    )

    print("[train_ppo_beer] Training finished – model saved.")


if __name__ == "__main__":
    main()
