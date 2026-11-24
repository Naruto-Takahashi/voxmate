import os
from pathlib import Path
from typing import Callable

from backends.agy import PersistentAgySession
from backends.claude import ClaudeCodeSession


def create_backend_session(
    workdir: Path,
    default_speaker_id: int,
    build_preamble_fn: Callable[[int], str],
    describe_step_fn: Callable[[dict], str],
    clean_for_speech_fn: Callable[[str], str],
):
    backend = os.environ.get("VOXMATE_BACKEND", "agy").strip().lower()
    if backend == "claude":
        return ClaudeCodeSession(
            workdir=workdir,
            default_speaker_id=default_speaker_id,
            build_preamble_fn=build_preamble_fn,
            describe_step_fn=describe_step_fn,
            clean_for_speech_fn=clean_for_speech_fn,
        )
    return PersistentAgySession(
        workdir=workdir,
        default_speaker_id=default_speaker_id,
        build_preamble_fn=build_preamble_fn,
        describe_step_fn=describe_step_fn,
        clean_for_speech_fn=clean_for_speech_fn,
    )
