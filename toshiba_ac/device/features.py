# Copyright 2022 Kamil Sroka

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import logging
import struct
import typing as t

from toshiba_ac.device.properties import (
    ToshibaAcMode,
    EstiaWaterMode,
    ToshibaAcStatus,
)
from toshiba_ac.utils import pretty_enum_name

logger = logging.getLogger(__name__)


class ToshibaAcFeatures:

    def __init__(
        self,
        ac_status: t.List[ToshibaAcStatus],
        ac_mode: t.List[ToshibaAcMode],
        ac_energy_report: bool,
    ) -> None:
        self._ac_status = ac_status
        self._ac_mode = ac_mode
        self._ac_energy_report = ac_energy_report

    @property
    def ac_status(self) -> t.List[ToshibaAcStatus]:
        return self._ac_status

    @property
    def ac_mode(self) -> t.List[ToshibaAcMode]:
        return self._ac_mode

    @property
    def ac_energy_report(self) -> bool:
        return self._ac_energy_report

    def __str__(self) -> str:
        return ", ".join(
            (
                f"Supported AC statuses: {{{', '.join(pretty_enum_name(e) for e in self.ac_status)}}}",
                f"Supported AC modes: {{{', '.join(pretty_enum_name(e) for e in self.ac_mode)}}}",
                f"Supported AC energy report: {'Yes' if self.ac_energy_report else 'No'}",
            )
        )
