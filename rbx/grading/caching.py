import atexit
import io
import os
import pathlib
import shelve
import shutil
import tempfile
from typing import Any, Dict, List, Optional

from pydantic import BaseModel
from sqlitedict import SqliteDict

from rbx import console
from rbx.grading import grading_context
from rbx.grading.judge.cacher import FileCacher
from rbx.grading.judge.digester import digest_cooperatively
from rbx.grading.judge.storage import copyfileobj
from rbx.grading.profiling import Profiler
from rbx.grading.steps import (
    DigestHolder,
    GradingArtifacts,
    GradingFileOutput,
    GradingLogsHolder,
)

VERBOSE = False


class CacheInput(BaseModel):
    """
    The exact command that was executed, together with
    its set of input and output artifacts.

    This is used as a cache key, which means that, if across
    executions, the command, or the set of artifacts it
    consumes/produces changes, then there will be a cache key
    change, and thus the command will be re-run.
    """

    commands: List[str]
    artifacts: List[GradingArtifacts]
    extra_params: Dict[str, Any] = {}


class CacheFingerprint(BaseModel):
    """
    The state of the artifacts that are not stored in the
    cache key (usually for efficiency/key size reasons), such
    as the hashes of every FS input artifact, or the hashes of
    the produced artifacts.

    This is used for a few things:
        - Check whether the IO files have changed in disk since
          this command was cached, and evict this entry in such case.
        - Check whether the caching storage has changed since this
          command was cached, and evict this entry in such case.
        - Store small side-effects of the cached execution, such as
          execution time, memory, exit codes, etc.
    """

    digests: List[Optional[str]]
    fingerprints: List[str]
    output_fingerprints: List[str]
    logs: List[GradingLogsHolder]


class NoCacheException(Exception):
    pass


def _check_digests(artifacts_list: List[GradingArtifacts]):
    produced = set()
    for artifacts in artifacts_list:
        for input in artifacts.inputs:
            if input.digest is None:
                continue
            if input.digest.value is not None:
                continue
            if id(input.digest) not in produced:
                raise ValueError('Digests must be produced before being consumed')
        for output in artifacts.outputs:
            if output.digest is None:
                continue
            if output.digest.value is not None:
                continue
            if id(output.digest) in produced:
                raise ValueError('A digest cannot be produced more than once')
            produced.add(id(output.digest))


def _build_artifact_with_digest_list(
    artifacts_list: List[GradingArtifacts],
) -> List[GradingFileOutput]:
    outputs = []
    for artifacts in artifacts_list:
        for output in artifacts.outputs:
            if output.hash and output.digest is None:
                output.digest = DigestHolder()
            if output.digest is None:
                continue
            outputs.append(output)
    return outputs


def _build_digest_list(artifacts_list: List[GradingArtifacts]) -> List[DigestHolder]:
    outputs = _build_artifact_with_digest_list(artifacts_list)
    digests = []
    for output in outputs:
        assert output.digest is not None
        digests.append(output.digest)
    return digests


def _build_fingerprint_list(
    artifacts_list: List[GradingArtifacts], cacher: FileCacher
) -> List[str]:
    fingerprints = []
    for artifacts in artifacts_list:
        for input in artifacts.inputs:
            if input.src is None or not input.hash:
                continue
            if cacher.digest_from_symlink(input.src) is not None:
                continue
            with input.src.open('rb') as f:
                fingerprints.append(digest_cooperatively(f))
    return fingerprints


def _maybe_check_integrity(output: GradingFileOutput, integrity_digest: str):
    if not grading_context.should_check_integrity():
        return
    if not output.hash:
        return
    if output.dest is None or not output.dest.is_symlink() or not output.dest.is_file():
        # Only makes sense if the file EXISTS and IS A SYMLINK pointing to an
        # EXISTING storage file.
        # If the storage file ceases to exist, we can simply evict from the cache.
        return
    if output.digest is None:
        return
    with output.dest.open('rb') as f:
        output_digest = digest_cooperatively(f)
    if output_digest != integrity_digest:
        raise ValueError(
            f'Cache was tampered with, file {output.dest} has changed since it was cached.\nPlease run `rbx clean` to reset the cache.'
        )


def _check_digest_list_integrity(
    artifacts_list: List[GradingArtifacts], integrity_digests: List[Optional[str]]
):
    outputs = _build_artifact_with_digest_list(artifacts_list)
    assert len(outputs) == len(integrity_digests)
    for output, integrity_digest in zip(outputs, integrity_digests):
        assert output.digest is not None
        if integrity_digest is None:
            continue
        _maybe_check_integrity(output, integrity_digest)


def _build_output_fingerprint_list(
    artifacts_list: List[GradingArtifacts],
) -> List[str]:
    fingerprints = []
    for artifacts in artifacts_list:
        for output in artifacts.outputs:
            if output.dest is None or output.intermediate or output.hash:
                continue
            if not output.dest.is_file():
                fingerprints.append('')  # file does not exist
                continue
            with output.dest.open('rb') as f:
                fingerprints.append(digest_cooperatively(f))
    return fingerprints


def _build_logs_list(artifacts_list: List[GradingArtifacts]) -> List[GradingLogsHolder]:
    logs = []
    for artifacts in artifacts_list:
        if artifacts.logs is not None:
            logs.append(artifacts.logs)
    return logs


def _build_cache_fingerprint(
    artifacts_list: List[GradingArtifacts],
    cacher: FileCacher,
) -> CacheFingerprint:
    digests = [digest.value for digest in _build_digest_list(artifacts_list)]
    fingerprints = _build_fingerprint_list(artifacts_list, cacher)
    output_fingerprints = _build_output_fingerprint_list(
        artifacts_list,
    )

    logs = _build_logs_list(artifacts_list)
    return CacheFingerprint(
        digests=digests,
        fingerprints=fingerprints,
        output_fingerprints=output_fingerprints,
        logs=logs,
    )


def _fingerprints_match(
    fingerprint: CacheFingerprint, reference: CacheFingerprint
) -> bool:
    lhs, rhs = fingerprint.fingerprints, reference.fingerprints
    return tuple(lhs) == tuple(rhs)


def _output_fingerprints_match(
    fingerprint: CacheFingerprint, reference: CacheFingerprint
) -> bool:
    lhs, rhs = fingerprint.output_fingerprints, reference.output_fingerprints
    return tuple(lhs) == tuple(rhs)


def _build_cache_input(
    commands: List[str],
    artifact_list: List[GradingArtifacts],
    extra_params: Dict[str, Any],
    cacher: FileCacher,
) -> CacheInput:
    cloned_artifact_list = [
        artifacts.model_copy(deep=True) for artifacts in artifact_list
    ]
    for artifacts in cloned_artifact_list:
        # Clear logs from cache input, since they are not
        # part of the cache key.
        artifacts.logs = None

        for input in artifacts.inputs:
            if input.src is None:
                continue
            inferred_digest = cacher.digest_from_symlink(input.src)
            if inferred_digest is not None:
                # Consume cache from digest instead of file.
                input.digest = DigestHolder(value=inferred_digest)
                input.src = None

        for output in artifacts.outputs:
            if output.hash:
                # Cleanup dest field from hash artifacts
                # since they only their digest value should
                # be tracked by cache.
                output.dest = None

            if output.digest is not None:
                # Cleanup output digest value from cache input,
                # since it is not part of the cache key.
                output.digest.value = None
    return CacheInput(
        commands=commands, artifacts=cloned_artifact_list, extra_params=extra_params
    )


def _build_cache_key(input: CacheInput) -> str:
    with io.BytesIO(input.model_dump_json().encode()) as fobj:
        return digest_cooperatively(fobj)


def _copy_hashed_files(artifact_list: List[GradingArtifacts], cacher: FileCacher):
    for artifact in artifact_list:
        for output in artifact.outputs:
            if not output.hash or output.dest is None:
                continue
            assert output.digest is not None
            if output.optional and output.digest.value is None:
                continue
            assert output.digest.value is not None
            if (
                path_to_symlink := cacher.path_for_symlink(output.digest.value)
            ) is not None:
                # Use a symlink to the file in the persistent cache, if available.
                output.dest.unlink(missing_ok=True)
                output.dest.parent.mkdir(parents=True, exist_ok=True)
                output.dest.symlink_to(path_to_symlink)
            else:
                # Otherwise, copy it.
                with cacher.get_file(output.digest.value) as fobj:
                    with output.dest.open('wb') as f:
                        copyfileobj(fobj, f, maxlen=output.maxlen)
            if output.executable:
                output.dest.chmod(0o755)


def is_artifact_ok(artifact: GradingArtifacts, cacher: FileCacher) -> bool:
    for output in artifact.outputs:
        if output.optional or output.intermediate:
            continue
        if output.digest is not None:
            if output.digest.value is None or not cacher.exists(output.digest.value):
                return False
            return True
        assert output.dest is not None
        file_path: pathlib.Path = artifact.root / output.dest
        if not file_path.is_file():
            return False
        executable = os.access(str(file_path), os.X_OK)
        if executable != output.executable:
            return False
    return True


def are_artifacts_ok(artifacts: List[GradingArtifacts], cacher: FileCacher) -> bool:
    for artifact in artifacts:
        if not is_artifact_ok(artifact, cacher):
            return False
    return True


class DependencyCacheBlock:
    class Break(Exception):
        pass

    def __init__(
        self,
        cache: 'DependencyCache',
        commands: List[str],
        artifact_list: List[GradingArtifacts],
        extra_params: Dict[str, Any],
    ):
        self.cache = cache
        self.commands = commands
        self.artifact_list = artifact_list
        self.extra_params = extra_params
        self._key = None

    def __enter__(self):
        with Profiler('enter_in_cache'):
            if grading_context.is_no_cache():
                return False
            input = _build_cache_input(
                commands=self.commands,
                artifact_list=self.artifact_list,
                extra_params=self.extra_params,
                cacher=self.cache.cacher,
            )
            if VERBOSE:
                console.console.log(f'Cache input is: {input}')
            self._key = _build_cache_key(input)
            if VERBOSE:
                console.console.log(f'Cache key is: {self._key}')
            found = self.cache.find_in_cache(
                self.commands, self.artifact_list, self.extra_params, key=self._key
            )
            return found

    def __exit__(self, exc_type, exc_val, exc_tb):
        with Profiler('exit_in_cache'):
            if grading_context.is_no_cache():
                return True if exc_type is NoCacheException else None
            if exc_type is None:
                self.cache.store_in_cache(
                    self.commands, self.artifact_list, self.extra_params, key=self._key
                )
            if exc_type is NoCacheException:
                return True
            return None


class DependencyCache:
    root: pathlib.Path
    cacher: FileCacher

    def __init__(self, root: pathlib.Path, cacher: FileCacher):
        self.root = root
        self.cacher = cacher
        self.db = SqliteDict(self._cache_name(), autocommit=True)
        tmp_dir = pathlib.Path(tempfile.mkdtemp())
        self.transient_db = SqliteDict(str(tmp_dir / '.cache_db'), autocommit=True)
        atexit.register(lambda: self.db.close())
        atexit.register(lambda: self.transient_db.close())
        atexit.register(lambda: shutil.rmtree(tmp_dir, ignore_errors=True))

    def _cache_name(self) -> str:
        return str(self.root / '.cache_db')

    def get_db(self) -> shelve.Shelf:
        if grading_context.is_transient():
            return self.transient_db
        return self.db

    def _find_in_cache(self, key: str) -> Optional[CacheFingerprint]:
        return self.get_db().get(key)

    def _store_in_cache(self, key: str, fingerprint: CacheFingerprint):
        self.get_db()[key] = fingerprint

    def _evict_from_cache(self, key: str):
        db = self.get_db()
        if key in db:
            del db[key]

    def __call__(
        self,
        commands: List[str],
        artifact_list: List[GradingArtifacts],
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> DependencyCacheBlock:
        _check_digests(artifact_list)
        return DependencyCacheBlock(self, commands, artifact_list, extra_params or {})

    def find_in_cache(
        self,
        commands: List[str],
        artifact_list: List[GradingArtifacts],
        extra_params: Dict[str, Any],
        key: Optional[str] = None,
    ) -> bool:
        input = _build_cache_input(
            commands=commands,
            artifact_list=artifact_list,
            extra_params=extra_params,
            cacher=self.cacher,
        )
        key = key or _build_cache_key(input)

        fingerprint = self._find_in_cache(key)
        if fingerprint is None:
            return False

        reference_fingerprint = _build_cache_fingerprint(
            artifact_list,
            self.cacher,
        )

        if not _fingerprints_match(fingerprint, reference_fingerprint):
            self._evict_from_cache(key)
            return False

        if not _output_fingerprints_match(fingerprint, reference_fingerprint):
            self._evict_from_cache(key)
            return False

        # Check whether existing storage files were not tampered with.
        _check_digest_list_integrity(
            artifact_list,
            fingerprint.digests,
        )
        reference_digests = _build_digest_list(artifact_list)

        # Apply digest changes.
        old_digest_values = [digest for digest in reference_fingerprint.digests]
        for digest, reference_digest in zip(fingerprint.digests, reference_digests):
            reference_digest.value = digest

        if not are_artifacts_ok(artifact_list, self.cacher):
            # Rollback digest changes.
            for old_digest_value, reference_digest in zip(
                old_digest_values, reference_digests
            ):
                reference_digest.value = old_digest_value
            self._evict_from_cache(key)
            return False

        # Copy hashed files to file system.
        _copy_hashed_files(artifact_list, self.cacher)

        # Apply logs changes.
        for logs, reference_logs in zip(fingerprint.logs, reference_fingerprint.logs):
            if logs.run is not None:
                reference_logs.run = logs.run.model_copy(deep=True)
            if logs.interactor_run is not None:
                reference_logs.interactor_run = logs.interactor_run.model_copy(
                    deep=True
                )
            if logs.preprocess is not None:
                reference_logs.preprocess = [
                    log.model_copy(deep=True) for log in logs.preprocess
                ]
            reference_logs.cached = True

        return True

    def store_in_cache(
        self,
        commands: List[str],
        artifact_list: List[GradingArtifacts],
        extra_params: Dict[str, Any],
        key: Optional[str] = None,
    ):
        input = _build_cache_input(
            commands=commands,
            artifact_list=artifact_list,
            extra_params=extra_params,
            cacher=self.cacher,
        )
        key = key or _build_cache_key(input)

        if not are_artifacts_ok(artifact_list, self.cacher):
            return

        reference_fingerprint = _build_cache_fingerprint(
            artifact_list,
            self.cacher,
        )
        self._store_in_cache(
            key,
            reference_fingerprint,
        )
