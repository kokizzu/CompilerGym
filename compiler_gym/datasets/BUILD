# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.
load("@rules_python//python:defs.bzl", "py_library")

py_library(
    name = "datasets",
    srcs = [
        "__init__.py",
        "benchmark.py",
        "dataset.py",
        "files_dataset.py",
        "tar_dataset.py",
    ],
    visibility = ["//visibility:public"],
    deps = [
        "//compiler_gym:validation_result",
        "//compiler_gym/service/proto",
        "//compiler_gym/util",
    ],
)
