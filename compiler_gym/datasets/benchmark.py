# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.
import re
from concurrent.futures import as_completed
from pathlib import Path
from typing import Callable, Iterable, List, NamedTuple, Optional, Union

from compiler_gym.service.proto import Benchmark as BenchmarkProto
from compiler_gym.service.proto import File
from compiler_gym.util import thread_pool
from compiler_gym.util.decorators import memoized_property
from compiler_gym.validation_result import ValidationError

# A validation callback is a function that takes a single CompilerEnv instance
# as its argument and returns an iterable sequence of zero or more
# ValidationError tuples.
ValidationCallback = Callable[["CompilerEnv"], Iterable[ValidationError]]  # noqa: F821


# Regular expression that matches the full two-part URI prefix of a dataset:
#     {{protocol}}://{{dataset}}
#
# A trailing slash is permitted.
#
# Example matches: "benchmark://foo-v0", "benchmark://foo-v0/".
DATASET_NAME_RE = re.compile(
    r"(?P<dataset>(?P<dataset_protocol>[a-zA-z0-9-_]+)://(?P<dataset_name>[a-zA-z0-9-_]+-v(?P<dataset_version>[0-9]+)))/?"
)

# Regular expression that matches the full three-part format of a benchmark URI:
#     {{protocol}}://{{dataset}}/{{id}}
#
# The {{id}} is optional.
#
# Example matches: "benchmark://foo-v0/" or "benchmark://foo-v0/program".
BENCHMARK_URI_RE = re.compile(
    r"(?P<dataset>(?P<dataset_protocol>[a-zA-z0-9-_]+)://(?P<dataset_name>[a-zA-z0-9-_]+-v(?P<dataset_version>[0-9]+)))(/(?P<benchmark_name>[^\s]*))?$"
)


def resolve_uri_protocol(uri: str) -> str:
    """Require that the URI has a protocol by applying a default "benchmark"
    protocol if none is set."""
    if "://" not in uri:
        return f"benchmark://{uri}"
    return uri


class BenchmarkSource(NamedTuple):
    """A source file that is used to generate a benchmark. A benchmark may
    comprise many source files.
    """

    filename: str
    """The name of the file."""

    contents: bytes
    """The contents of the file as a byte array."""

    def __repr__(self) -> str:
        return str(self.filename)


class Benchmark(object):
    """A benchmark represents a particular program that is being compiled.

    A benchmark is a program that can be used by a :class:`CompilerEnv
    <compiler_gym.envs.CompilerEnv>` as a program to optimize. A benchmark
    comprises the data that is fed into the compiler, identified by a URI.

    Benchmarks are not normally instantiated directly. Instead, benchmarks are
    instantiated using :meth:`env.datasets.benchmark()
    <compiler_gym.datasets.Datasets.benchmark>`:

        >>> env.datasets.benchmark()
        benchmark://npb-v0/20

    Calling :meth:`env.datasets.benchmark()
    <compiler_gym.datasets.Datasets.benchmark>` with no arguments will select a
    benchmark randomly from the available datasets. To select a specific
    benchmark, pass the URI as argument:

        >>> env.datasets.benchmark("benchmark://npb-v0/20")
        benchmark://npb-v0/20

    The available benchmark URIs can be queried using
    :meth:`env.datasets.benchmark_uris()
    <compiler_gym.datasets.Datasets.benchmark_uris>`.

    Compiler environments may provide additional helper functions for generating
    benchmarks, such as :meth:`env.make_benchmark()
    <compiler_gym.envs.LlvmEnv.make_benchmark>` for LLVM.

    The data underlying a Benchmark instance should be considered immutable. New
    attributes cannot be assigned to Benchmark instances.

    Benchmarks may provide additional functionality such as runtime checks or
    methods for validating the semantics of a benchmark. The benchmark for an
    environment can be set during :meth:`env.reset()
    <compiler_gym.envs.CompilerEnv.reset>`. The currently active benchmark can
    be queried using :attr:`env.benchmark
    <compiler_gym.envs.CompilerEnv.benchmark>`:

        >>> env = gym.make("llvm-v0")
        >>> env.reset(benchmark="cbench-v1/crc32")
        >>> env.benchmark
        cbench-v1/crc32

    A Benchmark instance wraps an instance of the :code:`Benchmark` protocol
    buffer from the `RPC interface
    <https://github.com/facebookresearch/CompilerGym/blob/development/compiler_gym/service/proto/compiler_gym_service.proto>`_
    with additional functionality.
    """

    __slots__ = ["_proto", "_validation_callbacks", "_sources"]

    def __init__(
        self,
        proto: BenchmarkProto,
        validation_callbacks: Optional[List[ValidationCallback]] = None,
        sources: Optional[List[BenchmarkSource]] = None,
    ):
        self._proto = proto
        self._validation_callbacks = validation_callbacks or []
        self._sources = list(sources or [])

    def __repr__(self) -> str:
        return str(self.uri)

    @property
    def uri(self) -> str:
        """The URI of the benchmark.

        Benchmark URIs should be unique, that is, that two URIs with the same
        value should resolve to the same benchmark. However, URIs do not have
        uniquely describe a benchmark. That is, multiple identical benchmarks
        could have different URIs.

        :return: A URI string. :type: string
        """
        return self._proto.uri

    @property
    def proto(self) -> BenchmarkProto:
        """The protocol buffer representing the benchmark.

        :return: A Benchmark message.
        :type: :code:`Benchmark`
        """
        return self._proto

    @property
    def sources(self) -> Iterable[BenchmarkSource]:
        """The original source code used to produce this benchmark.

        :return: An iterable sequence of :class:`BenchmarkSource
            <compiler_gym.datasets.BenchmarkSource>` tuples, comprising relative
            file paths and file contents.

        :type: :code:`Iterable[BenchmarkSource]`
        """
        return (BenchmarkSource(*x) for x in self._sources)

    def is_validatable(self) -> bool:
        """Whether the benchmark has any validation callbacks registered.

        :return: :code:`True` if the benchmark has at least one validation
            callback.
        """
        return self._validation_callbacks != []

    def validate(self, env: "CompilerEnv") -> List[ValidationError]:  # noqa: F821
        """Run any validation callbacks and return any errors.

        If no errors are returned, validation has succeeded:

            >>> benchmark.validate(env)
            []

        If an error occurs, a :class:`ValidationError
        <compiler_gym.ValidationError>` tuple will describe the type of the
        error, and optionally contain other data:

            >>> benchmark.validate(env)
            [ValidationError(type="RuntimeError")]

        Multiple :class:`ValidationError <compiler_gym.ValidationError>` errors
        may be returned to indicate multiple errors.

        This is a synchronous version of :meth:`ivalidate()
        <compiler_gym.datasets.Benchmark.ivalidate>` that blocks until all
        results are ready:

            >>> benchmark.validate(env) == list(benchmark.ivalidate(env))
            True

        :param env: The :class:`CompilerEnv <compiler_gym.envs.CompilerEnv>`
            instance that is being validated.

        :return: A list of zero or more :class:`ValidationError
            <compiler_gym.ValidationError>` tuples that occurred during
            validation.
        """
        return list(self.ivalidate(env))

    def ivalidate(self, env: "CompilerEnv") -> Iterable[ValidationError]:  # noqa: F821
        """Run any validation callbacks and return a generator of errors.

        This is an asynchronous version of :meth:`validate()
        <compiler_gym.datasets.Benchmark.validate>` that returns immediately.

        :parameter env: A :class:`CompilerEnv <compiler_gym.envs.CompilerEnv>`
            instance to validate.

        :return: A generator of :class:`ValidationError
            <compiler_gym.ValidationError>` tuples that occur during validation.
        """
        executor = thread_pool.get_thread_pool_executor()
        futures = (
            executor.submit(validator, env) for validator in self.validation_callbacks()
        )
        for future in as_completed(futures):
            result: Iterable[ValidationError] = future.result()
            if result:
                yield from result

    def validation_callbacks(
        self,
    ) -> List[ValidationCallback]:
        """Return the list of registered validation callbacks.

        :return: A list of callables. See :meth:`add_validation_callback()
            <compiler_gym.datasets.Benchmark.add_validation_callback>`.
        """
        return self._validation_callbacks

    def add_source(self, source: BenchmarkSource) -> None:
        """Register a new source file for this benchmark.

        :param source: The :class:`BenchmarkSource
            <compiler_gym.envs.datasets.BenchmarkSource>` to register.
        """
        self._sources.append(source)

    def add_validation_callback(
        self,
        validation_callback: ValidationCallback,
    ) -> None:
        """Register a new validation callback that will be executed on
        :meth:`validate() <compiler_gym.datasets.Benchmark.validate>`.

        :param validation_callback: A callback that accepts a single
            :class:`CompilerEnv <compiler_gym.envs.CompilerEnv>` argument and
            returns an iterable sequence of zero or more :class:`ValidationError
            <compiler_gym.ValidationError>` tuples. Validation callbacks must be
            thread safe and must not modify the environment.
        """
        self._validation_callbacks.append(validation_callback)

    def write_sources_to_directory(self, directory: Path) -> int:
        """Write the source files for this benchmark to the given directory.

        This writes each of the :attr:`benchmark.sources
        <compiler_gym.datasets.Benchmark.sources>` files to disk.

        :param directory: The directory to write results to. If it does not
            exist, it is created.

        :return: The number of files written.
        """
        directory = Path(directory)
        directory.mkdir(exist_ok=True, parents=True)
        uniq_paths = set()
        for filename, contents in self.sources:
            path = directory / filename
            uniq_paths.add(path)
            path.parent.mkdir(exist_ok=True, parents=True)
            with open(path, "wb") as f:
                f.write(contents)

        return len(uniq_paths)

    @classmethod
    def from_file(cls, uri: str, path: Path):
        """Construct a benchmark from the path to a file.

        :param uri: The URI of the benchmark.

        :param path: A filesystem path.

        :raise FileNotFoundError: If the path does not exist.

        :return: A :class:`Benchmark <compiler_gym.datasets.Benchmark>` instance.
        """
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(path)
        return cls(
            proto=BenchmarkProto(
                uri=uri, program=File(uri=f"file:///{path.absolute()}")
            ),
        )

    @classmethod
    def from_file_contents(cls, uri: str, data: bytes):
        """Construct a benchmark from a raw data array.

        :param uri: The URI of the benchmark.

        :param data: An array of bytes that will be passed to the compiler
            service.
        """
        return cls(proto=BenchmarkProto(uri=uri, program=File(contents=data)))

    def __eq__(self, other: Union[str, "Benchmark"]):
        if isinstance(other, Benchmark):
            return self.uri == other.uri
        else:
            return self.uri == other

    def __ne__(self, other: Union[str, "Benchmark"]):
        return not self == other


class BenchmarkInitError(OSError):
    """Base class for errors raised if a benchmark fails to initialize."""


class BenchmarkWithSource(Benchmark):
    """A benchmark which has a single source file."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._src_name = None
        self._src_path = None

    @classmethod
    def create(
        cls, uri: str, input_path: Path, src_name: str, src_path: Path
    ) -> Benchmark:
        """Create a benchmark from paths."""
        benchmark = cls.from_file(uri, input_path)
        benchmark._src_name = src_name  # pylint: disable=protected-access
        benchmark._src_path = src_path  # pylint: disable=protected-access
        return benchmark

    @memoized_property
    def sources(self) -> Iterable[BenchmarkSource]:
        with open(self._src_path, "rb") as f:
            return [
                BenchmarkSource(filename=self._src_name, contents=f.read()),
            ]

    @property
    def source(self) -> str:
        """Return the single source file contents as a string."""
        return list(self.sources)[0].contents.decode("utf-8")
