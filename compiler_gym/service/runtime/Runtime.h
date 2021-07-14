// Copyright (c) Facebook, Inc. and its affiliates.
//
// This source code is licensed under the MIT license found in the
// LICENSE file in the root directory of this source tree.
#pragma once

#include "compiler_gym/service/runtime/CompilerGymService.h"
#include "compiler_gym/service/runtime/CreateAndRunCompilerGymServiceImpl.h"

namespace compiler_gym::runtime {

/**
 * Create and run an RPC service for the given compilation session.
 *
 * This should be called on its own in a self contained script to implement a
 * compilation service. Example:
 *
 * \code{.cpp}
 *     #include "compiler_gym/service/runtime/Runtime.h"
 *     #include "my_compiler_service/MyCompilationSession.h"
 *
 *     int main(int argc, char** argv) {
 *       createAndRunCompilerGymService<MyCompilationSession>(
 *           argc, argc, "My compiler service"
 *       );
 *     }
 * \endcode
 *
 * This function never returns.
 *
 * @tparam CompilationSessionType A sublass of CompilationSession that provides
 *    implementations of the abstract methods.
 */
template <typename CompilationSessionType>
[[noreturn]] void createAndRunCompilerGymService(int argc, char** argv, const char* usage) {
  createAndRunCompilerGymServiceImpl<CompilationSessionType>(argc, argv, usage);
}

}  // namespace compiler_gym::runtime
