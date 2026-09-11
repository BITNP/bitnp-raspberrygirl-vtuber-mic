from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np
import numpy.typing as npt

def get_available_providers() -> list[str]: ...
def preload_dlls(*, directory: str | None = None) -> None: ...

class NodeArg:
    name: str
    shape: Sequence[int | str | None]
    type: str

class InferenceSession:
    def __init__(
        self, path: str | Path, *, providers: Sequence[str]
    ) -> None: ...
    def get_providers(self) -> list[str]: ...
    def get_inputs(self) -> Sequence[NodeArg]: ...
    def get_outputs(self) -> Sequence[NodeArg]: ...
    def run(
        self,
        output_names: Sequence[str] | None,
        input_feed: Mapping[str, object],
        run_options: object | None = None,
    ) -> Sequence[npt.NDArray[np.generic]]: ...
