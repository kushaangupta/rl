# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.
from __future__ import annotations

import torch

from typing import Dict

from torchrl.data import TensorDict
from torchrl.envs import EnvBase

# This file is inspired by https://github.com/FelixOpolka/Single-Player-MCTS
# Refactoring involves: renaming, torch and tensordict compatibility and integration in torchrl's API

class MCTSPlanner():
    pass

class _MCTSNode:
    """Represents a node in the Monte-Carlo search tree. Each node holds a single environment state.

    Args:
        state (TensorDict): A tensordict representing the state of the node.
        n_actions (int): number of actions available at that stage.
        env (EnvBase): a stateless environment reading a state and an action
            through a step method.
        parent (_MCTSNode): a parent node.
        prev_action (int): the action that lead to this node.
        c_PUCT (float, optional): Exploration constant. Default: :obj:`1.38`.
        d_noise_alpha (float, optional): Dirichlet noise alpha parameter. Default: :obj:`0.03`.
        temp_threshold (int, optional): Number of steps into the episode after
            which we always select the action with highest action probability
            rather than selecting randomly.

    """

    def __init__(
        self,
        state: TensorDict,
        n_actions: int,
        env: EnvBase,
        parent: _MCTSNode,
        prev_action: int,
        c_PUCT: float=1.38,
    ):
        self.state = state
        self.n_actions = n_actions
        self.env = env
        self.parent = parent
        self.children = {}
        self.prev_action = prev_action

        self._is_expanded = False
        self._n_vlosses = 0  # Number of virtual losses on this node
        self._child_visit_count: torch.Tensor = torch.zeros([n_actions], dtype=torch.long)
        self._child_total_value: torch.Tensor = torch.zeros([n_actions])
        # Save copy of original prior before it gets mutated by dirichlet noise
        self._original_prior = torch.zeros([n_actions])
        self._child_prior = torch.zeros([n_actions])

    @property
    def visit_count(self) -> int:
        return self.parent._child_visit_count[self.prev_action]

    @visit_count.setter
    def visit_count(self, value):
        self.parent._child_visit_count[self.prev_action] = value

    @property
    def total_value(self):
        return self.parent._child_total_value[self.prev_action]

    @total_value.setter
    def total_value(self, value):
        self.parent._child_total_value[self.prev_action] = value

    @property
    def action_value(self):
        return self.total_value / (1 + self.visit_count)

    @property
    def child_U(self):
        return (c_PUCT * math.sqrt(1 + self.N) *
                self.child_prior / (1 + self.child_N))
