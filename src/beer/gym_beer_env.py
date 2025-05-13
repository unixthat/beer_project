from __future__ import annotations

"""Gym / Gymnasium compatible wrapper around the local battleship Board logic.

Observation
===========
2-channel (2, 10, 10) float32 tensor where
  chan 0 = 1.0 at coordinates already fired *and hit*
  chan 1 = 1.0 at coordinates already fired *and miss*
All zeros elsewhere.

Action space
============
Discrete(100) – flattened (row*10 + col) coordinate.

Reward (dense, simple)
======================
+1   hit (but not yet win)
+100 sink last ship  -> done=True
 0   miss first time at square
-1   repeat shot (hit or miss)

The wrapper is deliberately minimal; sophisticated shaping can be done by
passing a custom reward_dict to PPOBot.train().
"""

import numpy as np

# Prefer Gymnasium (≥0.29) to avoid Stable-Baselines3 compatibility warning.
try:
    import gymnasium as gym  # type: ignore
    from gymnasium import spaces  # type: ignore
    _USING_GYMNASIUM = True
except ModuleNotFoundError:  # Fall back to classic OpenAI Gym
    import gym  # type: ignore
    from gym import spaces  # type: ignore
    _USING_GYMNASIUM = False

from .battleship import Board, BOARD_SIZE, SHIPS

class BeerBattleshipEnv(gym.Env):
    metadata = {"render.modes": ["human"]}

    DEFAULT_REWARDS = {
        "hit":     5.0,
        "sink":   20.0,
        "miss":   -1.0,
        "repeat": -10.0,
        "win":    200.0,
        "adjacent": 0.5,  # extra bonus for a hit next to an earlier hit
    }


    def __init__(self, *, reward_dict: dict | None = None):
        super().__init__()
        self.board: Board | None = None
        self.action_space = spaces.Discrete(BOARD_SIZE * BOARD_SIZE)
        self.observation_space = spaces.Box(0.0, 1.0, shape=(2, BOARD_SIZE, BOARD_SIZE), dtype=np.float32)
        self._rewards = self.DEFAULT_REWARDS.copy()
        if reward_dict is not None:
            self._rewards.update(reward_dict)
        self._obs: np.ndarray | None = None

    # ------------------------------------------------------------------
    def reset(self, seed: int | None = None, **_):  # type: ignore[override]
        # Gymnasium requires forwarding the *seed* to super().reset
        if _USING_GYMNASIUM:
            super().reset(seed=seed)
        elif seed is not None:
            np.random.seed(seed)

        self.board = Board(size=BOARD_SIZE)
        self.board.place_ships_randomly(SHIPS)
        self._obs = np.zeros((2, BOARD_SIZE, BOARD_SIZE), dtype=np.float32)
        self.observation = self._obs  # For action masking

        # Return according to API version
        return (self._obs, {}) if _USING_GYMNASIUM else self._obs

    # ------------------------------------------------------------------
    def step(self, action: int):  # type: ignore[override]
        if self.board is None or self._obs is None:
            raise RuntimeError("Env must be reset before step")
        row, col = divmod(action, BOARD_SIZE)
        res, sunk = self.board.fire_at(row, col)
        reward = 0.0
        done = False
        if res == "hit":
            self._obs[0, row, col] = 1.0
            reward = self._rewards["hit"]

            # Proximity bonus: reward small extra if this hit is adjacent to a previous hit
            adj_bonus = self._rewards.get("adjacent", 0.0)
            if adj_bonus != 0.0:
                adjacent_hit = False
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        if dr == 0 and dc == 0:
                            continue
                        nr, nc = row + dr, col + dc
                        if 0 <= nr < BOARD_SIZE and 0 <= nc < BOARD_SIZE:
                            if self._obs[0, nr, nc] == 1.0:
                                adjacent_hit = True
                                break
                    if adjacent_hit:
                        break
                if adjacent_hit:
                    reward += adj_bonus

            if self.board.all_ships_sunk():
                reward = self._rewards["win"]
                done = True
            elif sunk is not None:
                # finished a single ship but game not over
                reward += self._rewards["sink"]
        elif res == "miss":
            self._obs[1, row, col] = 1.0
            reward = self._rewards["miss"]
        else:  # explicit repeat string from Board
            self._obs[1, row, col] = 1.0
            reward = self._rewards["repeat"]
        self.observation = self._obs  # For action masking

        info: dict = {}

        if _USING_GYMNASIUM:
            # 5-tuple expected by Gymnasium ≥0.29
            return self._obs, reward, done, False, info
        # Classic OpenAI-Gym expects 4-tuple
        return self._obs, reward, done, info

    # ------------------------------------------------------------------
    def render(self, mode="human"):
        if self.board:
            self.board.print_display_grid()
