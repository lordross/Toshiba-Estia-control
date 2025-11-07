# Copyright 2021 Kamil Sroka

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

import struct
import typing as t
import logging

logger = logging.getLogger(__name__)

from toshiba_estia.device.properties import (
    ToshibaAcMode,
    EstiaWaterMode,
    ToshibaAcStatus,
    EstiaCompressorStatus
)


class ToshibaAcFcuState:
    NONE_VAL = 0xFF
    NONE_VAL_HALF = 0x0F
    NONE_VAL_SIGNED = -1
    ENCODING_STRUCT = struct.Struct("BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB")

    class AcTemperature:
        @staticmethod
        def from_raw(raw: int) -> t.Optional[int]:
            return (raw - 32) / 2

    class EstiaTemperature:
        @staticmethod
        def from_raw(raw: int) -> t.Optional[int] | None:
            if raw == 0:
                return None
            else:
                return (raw - 48) / 2

    class EstiaWaterMode:
        @staticmethod
        def from_raw(raw: int) -> EstiaWaterMode:
            return {
                0x5: EstiaWaterMode.COOL,
                0x6: EstiaWaterMode.HEAT,
                0x0: EstiaWaterMode.NONE,
                # AUTO is unknown value
            }[raw]

    class AcStatus:
        @staticmethod
        def from_raw(raw: int) -> ToshibaAcStatus:
            return {
                0x30: ToshibaAcStatus.ON,
                0x31: ToshibaAcStatus.OFF,
                0x02: ToshibaAcStatus.NONE,
                ToshibaAcFcuState.NONE_VAL: ToshibaAcStatus.NONE,
            }[raw]

        @staticmethod
        def to_raw(status: ToshibaAcStatus) -> int:
            return {
                ToshibaAcStatus.ON: 0x30,
                ToshibaAcStatus.OFF: 0x31,
                ToshibaAcStatus.NONE: ToshibaAcFcuState.NONE_VAL,
            }[status]

    class AcMode:
        @staticmethod
        def from_raw(raw: int) -> ToshibaAcMode:
            return {
                0x41: ToshibaAcMode.AUTO,
                0x42: ToshibaAcMode.COOL,
                0x43: ToshibaAcMode.HEAT,
                0x00: ToshibaAcMode.NONE,
                ToshibaAcFcuState.NONE_VAL: ToshibaAcMode.NONE,
            }[raw]

        @staticmethod
        def to_raw(mode: ToshibaAcMode) -> int:
            return {
                ToshibaAcMode.AUTO: 0x41,
                ToshibaAcMode.COOL: 0x42,
                ToshibaAcMode.HEAT: 0x43,
                ToshibaAcMode.NONE: ToshibaAcFcuState.NONE_VAL,
            }[mode]

    @classmethod
    def from_hex_state(cls, hex_state: str) -> ToshibaAcFcuState:
        state = cls()
        state.decode(hex_state)
        return state

    def __init__(self) -> None:
        self._ac_status = ToshibaAcFcuState.NONE_VAL
        self._ac_mode = ToshibaAcFcuState.NONE_VAL
        self._ac_temperature = ToshibaAcFcuState.NONE_VAL_SIGNED

        # Status string
        self._status_string = ""

        # New world order
        self._dhw_is_enabled = 0
        self._dhw_target_temperature = 0
        self._new_outdoor_unit_dhw = 0
        self._new_heating_coil_dhw = 0
        self._new_heating_active = 0
        self._water_operation_mode = 0

        self._zone1_target_temperature = 0

        self._outdoor_unit_heat = 0
        self._heating_coil_heat = 0

        self._water_pump_status = 0

    def encode(self) -> str:
        return ""

    def decode(self, hex_state: str) -> None:

        self._status_string = hex_state

        data = self.ENCODING_STRUCT.unpack(bytes.fromhex(hex_state))
        (
            self._dhw_is_enabled,              # Byte 1 - DHW function enabled
            self._dhw_target_temperature,      # Byte 2 - DHW Target temperature
            self._new_outdoor_unit_dhw,        # Byte 3 - Outdoor unit active for DHW
            self._new_heating_coil_dhw,        # Byte 4 - Heater coils active for DHW
            self._new_heating_active,          # Byte 5 - Water function activated
            self._water_operation_mode,        # Byte 6 - Operation mode - Heat/Cool/Auto
            self._zone1_target_temperature,    # Byte 7 - Heating Target temperature
            _,                                 # Byte 8 - Old heating target temperature
            self._outdoor_unit_heat,           # Byte 9 - Outdoor unit active for heating
            self._heating_coil_heat,           # Byte 10 - Heating coil active for heating
            self._ac_outdoor_temperature,      # Byte 11
            _,                                 # Byte 12
            _,                                 # Byte 13
            _,                                 # Byte 14
            _,                                 # Byte 15
            _,                                 # Byte 16
            _,                                 # Byte 17
            _,                                 # Byte 18
            _,                                 # Byte 19
            self._water_pump_status,           # Byte 20 - Water pump status
            *_,
        ) = data

    def merge(self, input_string: str, state: str) -> str:

        logger.info(f"CURRENT STATE: {input_string}")
        logger.info(f"CHANGES:       {state}")

        # Convert strings to list of 2-char hex bytes for easier manipulation
        input_bytes = [input_string[i:i+2] for i in range(0, len(input_string), 2)]
        state_bytes = [state[i:i+2] for i in range(0, len(state), 2)]

        # Merge based on rules
        merged_bytes = []
        for i, input_byte in enumerate(input_bytes):
            if input_byte.lower() == 'ff':
                # Don't merge, keep existing state
                merged_bytes.append(state_bytes[i])
            else:
                # Merge: replace state with input value
                merged_bytes.append(input_byte)

        output_state = ''.join(merged_bytes)
        logger.info(f"NEW STATE:     {output_state}")
        return output_state


    def update(self, status_diff: str) -> bool:
        old_status_string = self._status_string
        state_update = self.merge(status_diff, old_status_string)

        self.decode(state_update)
        changed = True

        return changed

    def update_from_hbt(self, hb_data: t.Any) -> bool:
        changed = False

        if "iTemp" in hb_data and hb_data["iTemp"] != self._ac_indoor_temperature:
            self._ac_indoor_temperature = hb_data["iTemp"]
            changed = True

        if "oTemp" in hb_data and hb_data["oTemp"] != self._ac_outdoor_temperature:
            self._ac_outdoor_temperature = hb_data["oTemp"]
            changed = True

        return changed

    @property
    def ac_status(self) -> ToshibaAcStatus:
        return ToshibaAcFcuState.AcStatus.from_raw(self._ac_status)

    @ac_status.setter
    def ac_status(self, val: ToshibaAcStatus) -> None:
        self._ac_status = ToshibaAcFcuState.AcStatus.to_raw(val)

    @property
    def ac_mode(self) -> ToshibaAcMode:
        return ToshibaAcFcuState.AcMode.from_raw(self._ac_mode)

    @ac_mode.setter
    def ac_mode(self, val: ToshibaAcMode) -> None:
        self._ac_mode = ToshibaAcFcuState.AcMode.to_raw(val)

    @property
    def ac_temperature(self) -> t.Optional[int]:
        return ToshibaAcFcuState.AcTemperature.from_raw(self._ac_temperature)

    @ac_temperature.setter
    def ac_temperature(self, val: t.Optional[int]) -> None:
        self._ac_temperature = ToshibaAcFcuState.AcTemperature.to_raw(val)


    @property
    def ac_outdoor_temperature(self) -> t.Optional[int]:
        return ToshibaAcFcuState.AcTemperature.from_raw(self._ac_outdoor_temperature)

    @ac_outdoor_temperature.setter
    def ac_outdoor_temperature(self, val: t.Optional[int]) -> None:
        self._ac_outdoor_temperature = ToshibaAcFcuState.AcTemperature.to_raw(val)

    @property
    def dhw_target_temperature(self) -> t.Optional[int]:
        return ToshibaAcFcuState.AcTemperature.from_raw(self._dhw_target_temperature)

    @dhw_target_temperature.setter
    def dhw_target_temperature(self, val: t.Optional[int]) -> None:
        self._dhw_target_temperature = ToshibaAcFcuState.AcTemperature.to_raw(val)

    @property
    def dhw_target_temperature(self) -> t.Optional[int]:
        return ToshibaAcFcuState.AcTemperature.from_raw(self._dhw_target_temperature)

    @dhw_target_temperature.setter
    def dhw_target_temperature(self, val: t.Optional[int]) -> None:
        self._dhw_target_temperature = ToshibaAcFcuState.AcTemperature.to_raw(val)

    @property
    def zone1_target_temperature(self) -> t.Optional[int]:
        return ToshibaAcFcuState.AcTemperature.from_raw(self._zone1_target_temperature)

    @zone1_target_temperature.setter
    def zone1_target_temperature(self, val: t.Optional[int]) -> None:
        self._zone1_target_temperature = ToshibaAcFcuState.AcTemperature.to_raw(val)

    @property
    def compressor_status(self) -> t.Optional[EstiaCompressorStatus]:
        if self._new_outdoor_unit_dhw:
            return EstiaCompressorStatus.DHW

        if self._outdoor_unit_heat:
            return EstiaCompressorStatus.HEAT

        return EstiaCompressorStatus.OFF

    @property
    def zone1_mode(self) -> t.Optional[EstiaWaterMode]:
        return ToshibaAcFcuState.EstiaWaterMode.from_raw(self._water_operation_mode)

    @property
    def water_pump_is_running(self) -> t.Optional[bool]:
        return self._water_pump_status

    @property
    def electric_coil_dhw_is_active(self) -> t.Optional[bool]:
        return self._new_heating_coil_dhw

    @property
    def electric_coil_heat_is_active(self) -> t.Optional[bool]:
        return self._heating_coil_heat

    def __str__(self) -> str:
        res = f"Printing State"
        res += f", OperationModeWater: {self._water_operation_mode}" #
        res += f", Compressor(DHW/HEAT): {self._new_outdoor_unit_dhw}/{self._outdoor_unit_heat}"
        res += f", WaterPumpStatus: {self._water_pump_status}"
        return res
