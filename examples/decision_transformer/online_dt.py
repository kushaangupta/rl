# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.
"""Online Decision Transformer Example.
This is a self-contained example of an Online Decision Transformer training script.
The helper functions are coded in the utils.py associated with this script.
"""

import hydra
import torch
import tqdm

from torchrl.envs.libs.gym import set_gym_backend

from torchrl.envs.utils import ExplorationType, set_exploration_type
from torchrl.modules.tensordict_module import DecisionTransformerInferenceWrapper

from utils import (
    make_env,
    make_logger,
    make_odt_loss,
    make_odt_model,
    make_odt_optimizer,
    make_offline_replay_buffer,
)


@set_gym_backend("gym")  # D4RL uses gym so we make sure gymnasium is hidden
@hydra.main(config_path=".", config_name="odt_config")
def main(cfg: "DictConfig"):  # noqa: F821
    model_device = cfg.optim.device

    logger = make_logger(cfg)
    offline_buffer, obs_loc, obs_std = make_offline_replay_buffer(
        cfg.replay_buffer, cfg.env.reward_scaling
    )
    test_env = make_env(cfg.env, obs_loc, obs_std)

    actor = make_odt_model(cfg)
    policy = actor.to(model_device)

    loss_module = make_odt_loss(cfg.loss, policy)
    transformer_optim, temperature_optim, scheduler = make_odt_optimizer(
        cfg.optim, loss_module
    )
    inference_policy = DecisionTransformerInferenceWrapper(
        policy=policy,
        inference_context=cfg.env.inference_context,
    ).to(model_device)

    pbar = tqdm.tqdm(total=cfg.optim.pretrain_gradient_steps)

    r0 = None
    l0 = None
    pretrain_gradient_steps = cfg.optim.pretrain_gradient_steps
    clip_grad = cfg.optim.clip_grad
    eval_steps = cfg.logger.eval_steps
    pretrain_log_interval = cfg.logger.pretrain_log_interval
    reward_scaling = cfg.env.reward_scaling

    print(" ***Pretraining*** ")
    # Pretraining
    for i in range(pretrain_gradient_steps):
        pbar.update(i)
        data = offline_buffer.sample()
        # loss
        loss_vals = loss_module(data.to(model_device))
        transformer_loss = loss_vals["loss_log_likelihood"] + loss_vals["loss_entropy"]
        temperature_loss = loss_vals["loss_alpha"]

        transformer_optim.zero_grad()
        torch.nn.utils.clip_grad_norm_(policy.parameters(), clip_grad)
        transformer_loss.backward()
        transformer_optim.step()

        temperature_optim.zero_grad()
        temperature_loss.backward()
        temperature_optim.step()

        scheduler.step()

        # evaluation
        with torch.no_grad(), set_exploration_type(ExplorationType.MODE):
            inference_policy.eval()
            if i % pretrain_log_interval == 0:
                eval_td = test_env.rollout(
                    max_steps=eval_steps,
                    policy=inference_policy,
                    auto_cast_to_device=True,
                    break_when_any_done=False,
                )
                inference_policy.train()
        if r0 is None:
            r0 = eval_td["next", "reward"].sum(1).mean().item() / reward_scaling
        if l0 is None:
            l0 = transformer_loss.item()

        eval_reward = eval_td["next", "reward"].sum(1).mean().item() / reward_scaling
        if logger is not None:
            for key, value in loss_vals.items():
                logger.log_scalar(key, value.item(), i)
            logger.log_scalar("evaluation reward", eval_reward, i)

        pbar.set_description(
            f"[Pre-Training] loss: {transformer_loss.item(): 4.4f} (init: {l0: 4.4f}), evaluation reward: {eval_reward: 4.4f} (init={r0: 4.4f})"
        )


if __name__ == "__main__":
    main()
