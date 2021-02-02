# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.
"""Integrations tests for the LLVM CompilerGym environments."""

import numpy as np

from compiler_gym.envs import CompilerEnv
from tests.test_main import main

pytest_plugins = ["tests.envs.llvm.fixtures"]


def test_step(env: CompilerEnv, action_name: str):
    """Run each action on a single benchmark."""
    env.reward_space = "IrInstructionCount"
    env.observation_space = "Autophase"
    env.reset(benchmark="cBench-v0/crc32")
    observation, reward, done, info = env.step(
        env.action_space.from_string(action_name)
    )

    assert isinstance(observation, np.ndarray)
    assert observation.shape == (56,)
    assert isinstance(reward, float)
    assert isinstance(done, bool)


if __name__ == "__main__":
    main()
