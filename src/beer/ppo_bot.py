from __future__ import annotations

"""Light-weight PPO integration for Battleship

This module follows the quick-start recipe discussed in chat and provides:

1. ``train()`` – minimal Stable-Baselines 3 PPO training loop on the
   *gym-battleship* environment.  The default hyper-parameters mirror the
   example so that a competent model (≈65 % win-rate vs. random) can be
   trained on an Apple M-series CPU in < 1 hour.
2. ``load()`` – load a previously-saved model from *ppo_battleship.zip*.
3. ``next_shot()`` – given a 100-element 0/1 board-history vector
   (0 = unseen, 1 = already fired), return the *(row, col)* coordinate the
   policy wants to fire at **deterministically** (no exploration).

Nothing in here is imported by the packaged bot or the unit-tests so it will
*not* interfere with the existing deterministic strategy unless you
explicitly opt in.
"""

from pathlib import Path
from typing import Iterable, Sequence, Tuple, Any

import numpy as np
import importlib
import contextlib
import torch
import multiprocessing
import zipfile

# ---------------------------------------------------------------------------
# Optional heavy imports – executed lazily so the module can be imported even
# inside constrained CI jobs that do not have the RL stack available.
# ---------------------------------------------------------------------------
_SB3_AVAILABLE = False
with contextlib.suppress(ModuleNotFoundError):
    from stable_baselines3 import PPO  # noqa: F401  – re-import later lazily

    _SB3_AVAILABLE = True
# sb3-contrib (MaskablePPO) is optional.  Fallback to standard PPO if absent.
try:
    from sb3_contrib import MaskablePPO as _MaskablePPO  # type: ignore
except ModuleNotFoundError:  # pragma: no cover – maskable not installed
    _MaskablePPO = None  # type: ignore

# Gym family imports are also lazy inside the training helper.


# ---------------------------------------------------------------------------
# Custom CNN feature extractor for 10×10 boards – optional but yields ~3-5
# fewer shots on average than a plain MLP.  Needs to be defined early so the
# CLI branch can reference it.
# ---------------------------------------------------------------------------

if _SB3_AVAILABLE:
    import torch
    import torch.nn as nn  # noqa: E402
    from stable_baselines3.common.torch_layers import BaseFeaturesExtractor  # noqa: E402

    class _GridCNN(BaseFeaturesExtractor):  # type: ignore[misc]
        """Two 3×3 conv layers + linear tail (suitable for 10×10 inputs)."""

        def __init__(self, observation_space: Any, features_dim: int = 256):
            super().__init__(observation_space, features_dim)
            n_input_channels = observation_space.shape[0]

            self.cnn = nn.Sequential(
                nn.Conv2d(n_input_channels, 32, kernel_size=3, stride=1, padding=1),
                nn.ReLU(),
                nn.Conv2d(32, 64, kernel_size=3, stride=1, padding=1),
                nn.ReLU(),
            )

            # Compute shape by doing one forward pass with a dummy tensor
            with torch.no_grad():
                sample = torch.as_tensor(observation_space.sample()[None]).float()
                n_flatten = int(np.prod(self.cnn(sample).shape[1:]))

            self.linear = nn.Sequential(
                nn.Flatten(),
                nn.Linear(n_flatten, features_dim),
                nn.ReLU(),
            )

        def forward(self, observations):  # type: ignore[override]
            return self.linear(self.cnn(observations))


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_THIS_DIR = Path(__file__).resolve().parent
DEFAULT_MODEL_PATH = _THIS_DIR / "ppo_battleship.zip"


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _action_mask_from_obs(obs: np.ndarray) -> np.ndarray:
    """Return a 100-element **bool** mask where True = square has **not** been fired.

    Accepts all three observation variants we might encounter:

    1. Flat 100-vector (training history passed in ``next_shot``)
    2. (10, 10) single-channel grid (legacy env)
    3. (2, 10, 10) hits/misses tensor (BeerBattleshipEnv & Gymnasium version)
    """

    obs = np.asarray(obs)

    if obs.shape == (100,):  # flat vector: 0 = fresh, 1 = fired
        return obs == 0

    if obs.shape == (10, 10):  # single channel board
        return np.logical_not(obs.astype(bool)).flatten()

    if obs.shape == (2, 10, 10):  # our 2-channel format: chan0=hit, chan1=miss
        fired = (obs[0] + obs[1]).astype(bool)
        return np.logical_not(fired).flatten()

    # Fallback – flatten and assume 0 = legal as in case (1)
    flat = obs.reshape(-1)
    return flat == 0


def _lazy_imports() -> None:  # pragma: no cover – helper for training path
    """Import heavy RL libs only when required."""
    global PPO, _MaskablePPO, gym, gym_battleship, make_vec_env, ActionMasker

    try:
        gym = importlib.import_module("gymnasium")  # type: ignore
    except ModuleNotFoundError:
        gym = importlib.import_module("gym")  # type: ignore

    gym_battleship = importlib.import_module("gym_battleship")  # noqa: F401
    make_vec_env = importlib.import_module("stable_baselines3.common.env_util").make_vec_env  # type: ignore
    if _MaskablePPO is not None:
        ActionMasker = importlib.import_module("sb3_contrib.common.wrappers").ActionMasker  # type: ignore
    else:
        ActionMasker = None  # type: ignore

    # Gym <=0.26 expects numpy.bool8, removed in NumPy 2.0. Re-add alias if missing.
    import numpy as _np
    if not hasattr(_np, "bool8"):
        _np.bool8 = _np.bool_


# ---------------------------------------------------------------------------
# Inference API
# ---------------------------------------------------------------------------
_model = None  # cached loaded policy


def load(model_path: Path | str = DEFAULT_MODEL_PATH, masked: bool | None = None):
    """Load a PPO or MaskablePPO model from *model_path* (cached).
    If masked is None, auto-detect from the saved model.
    """
    if not _SB3_AVAILABLE:
        raise ImportError("stable-baselines3 must be installed to load PPO model")

    global _model
    if _model is None:
        path = Path(model_path)
        if not path.exists():
            raise FileNotFoundError(f"No PPO model found at {path}. Run train() first.")
        # Auto-detect MaskablePPO vs PPO from the saved zip
        is_maskable = False
        if masked is None:
            try:
                with zipfile.ZipFile(path, 'r') as archive:
                    data = archive.read('data.pkl')
                    # Heuristic: search for any occurrence of the substring "Maskable"
                    if b"Maskable" in data:
                        is_maskable = True
            except Exception:
                pass
        else:
            is_maskable = masked

        def _try_maskable():
            if _MaskablePPO is None:
                raise ImportError("sb3-contrib (MaskablePPO) is required for this model but not installed")
            return _MaskablePPO.load(str(path))

        try:
            if is_maskable:
                _model = _try_maskable()
            else:
                _model = PPO.load(str(path))
        except (TypeError, ValueError) as exc:
            # A common failure mode: archive created with MaskablePPO but loaded as PPO
            # manifests as unexpected kwargs like 'use_sde'. If that happens, fall back.
            if _MaskablePPO is not None and not is_maskable:
                try:
                    _model = _try_maskable()
                    print("[ppo_bot] Auto-corrected: loaded model with MaskablePPO after PPO.load failed.")
                except Exception:
                    raise exc
            else:
                raise exc
    return _model


def next_shot(board_history: Sequence[int] | np.ndarray) -> Tuple[int, int]:
    """Return (row, col) fired by the deterministic PPO policy."""
    if not _SB3_AVAILABLE:
        raise ImportError("stable-baselines3 must be installed to use next_shot()")

    obs = np.asarray(board_history, dtype=np.float32)
    # Accept both (100,) and (2, 10, 10) for compatibility
    if obs.shape == (100,):
        obs = obs.reshape(2, 10, 10)  # If you ever use flat input, reshape (optional)
    # If obs.shape == (2, 10, 10), do nothing
    # Otherwise, let model/predict throw a clear error

    model = load()
    mask = _action_mask_from_obs(obs)
    try:
        action, _ = model.predict(obs, deterministic=True, action_masks=mask)
    except TypeError:
        action, _ = model.predict(obs, deterministic=True)
        if not mask[action]:
            action = int(np.flatnonzero(mask)[0])

    row, col = divmod(int(action), 10)
    return row, col


# ---------------------------------------------------------------------------
# Training helper – goes beyond unit-test scope but useful for users.
# ---------------------------------------------------------------------------

def beer_mask_fn(env):
    """Smarter action mask.

    1.  If no hits so far → allow any not-yet-fired square (same as before).
    2.  Once at least one *hit* exists, restrict the legal moves to the
        *orthogonal* neighbours (N,E,S,W) of every hit **that have not been
        fired yet**.  This focuses the policy on finishing the current ship
        first.  If that restricted set is empty (rare edge-case right after a
        sink) we fall back to rule 1 so the game can continue normally.
    """

    obs = env._obs  # (2, 10, 10) tensor: chan0 = hits, chan1 = misses
    fired = (obs[0] + obs[1]).astype(bool)        # any fired square
    hits = obs[0].astype(bool)

    if hits.any():
        target_mask = np.zeros_like(hits, dtype=bool)
        # orthogonal neighbours of hits
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            shifted = np.roll(hits, shift=(dr, dc), axis=(0, 1))
            # Zero-out wrap-around artefacts introduced by np.roll
            if dr == -1:
                shifted[-1, :] = False
            if dr == 1:
                shifted[0, :] = False
            if dc == -1:
                shifted[:, -1] = False
            if dc == 1:
                shifted[:, 0] = False
            target_mask |= shifted

        legal = np.logical_and(~fired, target_mask)
        if legal.any():
            return legal.flatten()

    # Fallback: any square not yet fired
    return (~fired).flatten()


def train(
    total_timesteps: int = 2_000_000,
    *,
    n_envs: int = 8,
    reward_dict: dict | None = None,
    masked: bool = True,
    model_path: Path | str = DEFAULT_MODEL_PATH,
    stop_mean_shots: int | None = None,
    eval_freq: int = 200_000,
    eval_episodes: int = 30,
    **ppo_kwargs,
):
    """Train a PPO (or MaskablePPO) policy and save it to *model_path*.

    This is a minimal reproduction of the shell recipe provided in chat.  It
    purposely uses SB3 defaults (slightly tweaked batch sizes) so that the
    behaviour is reproducible across machines.
    """
    _lazy_imports()

    # ------------------------------------------------------------------
    # Environment factory – Gym API 0.29+
    # ------------------------------------------------------------------
    def _make_env():
        env_kwargs = {}
        if reward_dict is not None:
            env_kwargs["reward_dictionary"] = reward_dict
        try:
            from .gym_beer_env import BeerBattleshipEnv
            return BeerBattleshipEnv(reward_dict=reward_dict)
        except Exception:
            # fallback to external gym-battleship env if wrapper import fails
            return gym.make("Battleship-v0", **env_kwargs)  # type: ignore[arg-type]

    if masked and _MaskablePPO is None:
        raise ImportError("sb3-contrib must be installed for MaskablePPO")

    def _factory():
        env = _make_env()
        if not hasattr(env, "seed"):
            env.seed = lambda _=None: None  # type: ignore[assignment]
        original_step = env.step  # type: ignore[attr-defined]
        def _step_cast(a):  # type: ignore[override]
            if isinstance(a, np.integer):
                a = int(a)
            return original_step(a)
        env.step = _step_cast  # type: ignore[assignment]
        if masked:
            from sb3_contrib.common.wrappers import ActionMasker
            env = ActionMasker(env, beer_mask_fn)
        return env

    # Use multi-process vector env when more than one environment to fully utilise CPU cores
    from stable_baselines3.common.vec_env import SubprocVecEnv
    vec_env = make_vec_env(_factory, n_envs=n_envs, vec_env_cls=SubprocVecEnv if n_envs > 1 else None)

    Algo = _MaskablePPO if masked else PPO

    # Automatically select Apple Silicon "mps" backend if available
    device = "mps" if torch.backends.mps.is_available() else "cpu"

    # Allow caller to override policy via ppo_kwargs (e.g. "CnnPolicy")
    policy_name = ppo_kwargs.pop("policy", "MlpPolicy")

    model = Algo(
        policy_name,
        vec_env,
        n_steps=4096,           # longer rollouts -> more stable updates, fewer iterations
        batch_size=1024,
        verbose=1,
        tensorboard_log=None,
        device=device,
        **ppo_kwargs,
    )

    # --------------------------------------------------------------
    # Incremental training with evaluation & early stopping
    # --------------------------------------------------------------

    def _eval_mean_shots(policy) -> float:
        """Play *eval_episodes* games and return average number of shots taken."""
        env_eval = _make_env()  # single-instance env, not vectorised
        lengths = []
        for _ in range(eval_episodes):
            obs_tuple = env_eval.reset()
            # Gymnasium returns (obs, info); older Gym returns obs only.
            if isinstance(obs_tuple, tuple) and len(obs_tuple) == 2:
                obs, _info_reset = obs_tuple  # type: ignore[misc]
            else:
                obs = obs_tuple  # type: ignore[assignment]
            done = False
            steps = 0
            while not done:
                # Guarantee channel dimension: if observation is (10,10) or (1,10,10) make it (2,10,10)
                if obs.ndim == 2:
                    obs = np.stack([obs, np.zeros_like(obs)], axis=0)
                elif obs.ndim == 3 and obs.shape[0] == 1:
                    obs = np.concatenate([obs, np.zeros_like(obs)], axis=0)

                # Use the same smart mask as during training for fair evaluation
                mask_vec = beer_mask_fn(env_eval)  # (100,)

                # Ensure batch dimension for SB3 predict
                obs_batch = obs if obs.ndim == 4 else np.expand_dims(obs, 0)
                mask_batch = mask_vec if mask_vec.ndim == 2 else np.expand_dims(mask_vec, 0)

                try:
                    action, _ = policy.predict(
                        obs_batch,
                        deterministic=True,
                        action_masks=mask_batch if (_MaskablePPO and isinstance(policy, _MaskablePPO)) else None,
                    )
                except TypeError:
                    action, _ = policy.predict(obs_batch, deterministic=True)  # type: ignore[arg-type]

                # Remove batch dim / convert to int
                if isinstance(action, np.ndarray):
                    action = int(action[0]) if action.ndim > 0 else int(action)

                step_out = env_eval.step(action)  # type: ignore[misc]
                if len(step_out) == 5:
                    obs, _r, terminated, truncated, _info = step_out  # type: ignore[assignment]
                    done = terminated or truncated
                else:
                    obs, _r, done, _info = step_out  # type: ignore[assignment]
                steps += 1
            lengths.append(steps)
        env_eval.close()
        return float(np.mean(lengths))

    try:
        steps_done = 0
        while steps_done < total_timesteps:
            chunk = min(eval_freq, total_timesteps - steps_done)
            model.learn(total_timesteps=chunk, reset_num_timesteps=False, progress_bar=True)
            steps_done += chunk

            if stop_mean_shots is not None:
                mean_shots = _eval_mean_shots(model)
                print(f"[ppo_bot] Eval: mean shots = {mean_shots:.2f} (target ≤ {stop_mean_shots}) after {steps_done} steps")
                if mean_shots <= stop_mean_shots:
                    print("[ppo_bot] Early stopping criterion met – finishing training.")
                    break
    finally:
        # Always save the current weights, even on Ctrl-C
        model.save(str(model_path))
        print(f"[ppo_bot] Model saved to {model_path}")

    return model


# ---------------------------------------------------------------------------
# CLI entry-point: ``python -m beer.ppo_bot --train`` etc.
# ---------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover – not exercised by test-suite
    import argparse

    parser = argparse.ArgumentParser(description="Train or run PPO Battleship agent")
    sub = parser.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("train", help="Train PPO and save to disk")
    t.add_argument("--timesteps", type=int, default=2_000_000, help="Total PPO timesteps")
    t.add_argument("--envs", type=int, default=8, help="Number of parallel envs")
    t.add_argument("--no-mask", action="store_true", help="Disable action-masking even if sb3-contrib is present")
    t.add_argument("--out", default=str(DEFAULT_MODEL_PATH), help="Model output path (.zip)")
    t.add_argument("--stop-shots", type=int, help="Early stop when mean shots per game ≤ this value (evaluated every --eval-freq steps)")
    t.add_argument("--eval-freq", type=int, default=200_000, help="Timesteps between evals for early stopping")
    t.add_argument("--eval-episodes", type=int, default=30, help="Episodes per evaluation for early stopping")
    t.add_argument("--small-cnn", action="store_true", help="Use custom compact CNN features extractor (GridCNN)")
    t.add_argument("--ppo-kwargs", type=str, help="JSON dict with extra PPO constructor kwargs (e.g., '{\"learning_rate\": 1e-4}')")

    r = sub.add_parser("shot", help="Query next shot for dummy board vector read from STDIN")
    r.add_argument("model", nargs="?", default=str(DEFAULT_MODEL_PATH), help="Path to trained model")

    m = sub.add_parser("mask-test", help="Run a quick mask test for debugging")

    rsm = sub.add_parser("resume", help="Continue training from an existing model")
    rsm.add_argument("model",           help="Path to .zip to resume")
    rsm.add_argument("--timesteps",     type=int, required=True)
    rsm.add_argument("--envs",          type=int, default=8)
    rsm.add_argument("--ppo-kwargs", type=str, help="JSON dict with PPO kwargs to override before resuming")
    rsm.add_argument("--stop-shots",   type=int, help="Early stop when mean shots per game ≤ this value (evaluated every --eval-freq steps)")
    rsm.add_argument("--eval-freq",    type=int, default=200_000, help="Timesteps between evals for early stopping")
    rsm.add_argument("--eval-episodes", type=int, default=30, help="Episodes per evaluation for early stopping")

    args = parser.parse_args()

    if args.cmd == "train":
        import json
        extra_kwargs = json.loads(args.ppo_kwargs) if args.ppo_kwargs else {}
        if args.small_cnn:
            gridcnn_kwargs = {
                "features_extractor_class": _GridCNN,
                "features_extractor_kwargs": {"features_dim": 256},
            }
            extra_kwargs.setdefault("policy_kwargs", gridcnn_kwargs)
            extra_kwargs.setdefault("policy", "CnnPolicy")  # handled inside train()

        train(
            total_timesteps=args.timesteps,
            n_envs=args.envs,
            masked=not args.no_mask,
            model_path=args.out,
            stop_mean_shots=args.stop_shots,
            eval_freq=args.eval_freq,
            eval_episodes=args.eval_episodes,
            **extra_kwargs,
        )
    elif args.cmd == "shot":
        import sys, json

        board_vec = json.loads(sys.stdin.read())
        row, col = next_shot(board_vec)
        print(json.dumps({"row": row, "col": col}))
    elif args.cmd == "mask-test":
        from beer.gym_beer_env import BeerBattleshipEnv
        env = BeerBattleshipEnv()
        env.reset()
        fired_mask = beer_mask_fn(env)
        print("legal after reset =", fired_mask.sum())  # should be 100
        # Mark a cell as fired and check again
        env._obs[0, 0, 0] = 1.0
        fired_mask2 = beer_mask_fn(env)
        print("legal after firing (0,0) =", fired_mask2.sum())  # should be 99
    elif args.cmd == "resume":
        import json, sys
        _lazy_imports()
        extra_cfg = json.loads(args.ppo_kwargs) if args.ppo_kwargs else {}
        model = load(args.model)                       # auto-detect mask
        # Apply optional hyper-parameter overrides
        for _k, _v in extra_cfg.items():
            if hasattr(model, _k):
                setattr(model, _k, _v)
            else:
                print(f"[ppo_bot] Warning: model has no attribute '{_k}' – ignored.", file=sys.stderr)

        # --- Recreate environment factory identical to `train()` ---
        def _make_env():
            try:
                from .gym_beer_env import BeerBattleshipEnv
                return BeerBattleshipEnv()
            except Exception:
                return gym.make("Battleship-v0")  # type: ignore[arg-type]

        def _factory():
            env = _make_env()
            if not hasattr(env, "seed"):
                env.seed = lambda _=None: None  # type: ignore[assignment]
            original_step = env.step  # type: ignore[attr-defined]
            def _step_cast(a):  # type: ignore[override]
                if isinstance(a, np.integer):
                    a = int(a)
                return original_step(a)
            env.step = _step_cast  # type: ignore[assignment]
            if _MaskablePPO is not None and isinstance(model, _MaskablePPO):
                from sb3_contrib.common.wrappers import ActionMasker
                env = ActionMasker(env, beer_mask_fn)
            return env

        from stable_baselines3.common.vec_env import SubprocVecEnv
        vec_env = make_vec_env(_factory, n_envs=args.envs, vec_env_cls=SubprocVecEnv if args.envs > 1 else None)
        model.set_env(vec_env)

        # --------------------------------------------------------------
        # Optional early stopping based on mean shots, mirroring train().
        # --------------------------------------------------------------

        def _eval_mean_shots(policy) -> float:
            env_eval = _make_env()
            lengths = []
            for _ in range(args.eval_episodes):
                obs_tuple = env_eval.reset()
                if isinstance(obs_tuple, tuple) and len(obs_tuple) == 2:
                    obs, _ = obs_tuple
                else:
                    obs = obs_tuple
                done = False
                steps = 0
                while not done:
                    if obs.ndim == 2:
                        obs = np.stack([obs, np.zeros_like(obs)], axis=0)
                    elif obs.ndim == 3 and obs.shape[0] == 1:
                        obs = np.concatenate([obs, np.zeros_like(obs)], axis=0)

                    # Align evaluation with training: smart target-mode mask
                    mask_vec = beer_mask_fn(env_eval)  # (100,)

                    # Ensure batch dimension for SB3 predict
                    obs_batch = obs if obs.ndim == 4 else np.expand_dims(obs, 0)
                    mask_batch = mask_vec if mask_vec.ndim == 2 else np.expand_dims(mask_vec, 0)

                    try:
                        action, _ = policy.predict(
                            obs_batch,
                            deterministic=True,
                            action_masks=mask_batch if (_MaskablePPO and isinstance(policy, _MaskablePPO)) else None,
                        )
                    except TypeError:
                        action, _ = policy.predict(obs_batch, deterministic=True)  # type: ignore[arg-type]

                    # Remove batch dim / convert to int
                    if isinstance(action, np.ndarray):
                        action = int(action[0]) if action.ndim > 0 else int(action)

                    step_out = env_eval.step(action)
                    if len(step_out) == 5:
                        obs, _r, terminated, truncated, _info = step_out
                        done = terminated or truncated
                    else:
                        obs, _r, done, _info = step_out
                    steps += 1
                lengths.append(steps)
            env_eval.close()
            return float(np.mean(lengths))

        try:
            steps_done = 0
            while steps_done < args.timesteps:
                chunk = min(args.eval_freq, args.timesteps - steps_done) if args.stop_shots is not None else (args.timesteps - steps_done)
                model.learn(total_timesteps=chunk, reset_num_timesteps=False, progress_bar=True)
                steps_done += chunk

                if args.stop_shots is not None:
                    mean_shots = _eval_mean_shots(model)
                    print(f"[ppo_bot] Eval: mean shots = {mean_shots:.2f} (target ≤ {args.stop_shots}) after {steps_done} steps")
                    if mean_shots <= args.stop_shots:
                        print("[ppo_bot] Early stopping criterion met – finishing training.")
                        break
        finally:
            model.save(args.model)
            print(f"[ppo_bot] Model saved to {args.model}")
