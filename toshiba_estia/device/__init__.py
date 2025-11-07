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

import asyncio
import logging
import struct
import typing as t
from dataclasses import dataclass

from toshiba_estia.device.fcu_state import ToshibaAcFcuState
from toshiba_estia.device.features import ToshibaAcFeatures
from toshiba_estia.device.properties import (

    ToshibaAcDeviceEnergyConsumption,
    ToshibaAcMode,
    ToshibaAcStatus,
    EstiaCompressorStatus,
    EstiaWaterMode,
)
from toshiba_estia.utils import async_sleep_until_next_multiply_of_minutes, pretty_enum_name, ToshibaAcCallback
from toshiba_estia.utils.amqp_api import ToshibaAcAmqpApi, JSONSerializable
from toshiba_estia.utils.http_api import ToshibaAcHttpApi

logger = logging.getLogger(__name__)


class ToshibaAcDeviceError(Exception):
    pass


class ToshibaAcDeviceCallback(ToshibaAcCallback["ToshibaAcDevice"]):
    pass


class ToshibaAcDevice:
    STATE_RELOAD_PERIOD_MINUTES = 30

    def __init__(
        self,
        name: str,
        device_id: str,
        ac_id: str,
        ac_unique_id: str,
        initial_ac_state: str,
        firmware_version: str,
        merit_feature: str,
        ac_model_id: str,
        amqp_api: ToshibaAcAmqpApi,
        http_api: ToshibaAcHttpApi,
    ) -> None:
        self.name = name
        self.device_id = device_id
        self.ac_id = ac_id
        self.ac_unique_id = ac_unique_id
        self.firmware_version = firmware_version
        self.amqp_api = amqp_api
        self.http_api = http_api

        self.fcu_state = ToshibaAcFcuState.from_hex_state(initial_ac_state)

        self.cdu: t.Optional[str] = None
        self.fcu: t.Optional[str] = None
        self.serial_number: t.Optional[str] = None
        self._water_flow_rate: t.Optional[int] = 0

        self._on_state_changed_callback = ToshibaAcDeviceCallback()
        self._on_energy_consumption_changed_callback = ToshibaAcDeviceCallback()
        self._ac_energy_consumption: t.Optional[ToshibaAcDeviceEnergyConsumption] = None
        self.periodic_reload_state_task: t.Optional[asyncio.Task[None]] = None

    async def connect(self) -> None:
        await self.load_additional_device_info()
        self.periodic_reload_state_task = asyncio.get_running_loop().create_task(self.periodic_state_reload())

    async def shutdown(self) -> None:
        if self.periodic_reload_state_task:
            self.periodic_reload_state_task.cancel()
            await self.periodic_reload_state_task

    async def load_additional_device_info(self) -> None:
        additional_info = await self.http_api.get_device_additional_info(self.ac_unique_id)
        self.cdu = additional_info.cdu
        self.fcu = additional_info.fcu
        self.serial_number = additional_info.serial_number
        self.temperatures = additional_info.temperatures

        await self.on_state_changed_callback(self)

    async def state_reload(self) -> None:
        hex_state = await self.http_api.get_device_state(self.ac_unique_id)
        logger.debug(f"[{self.name}] AC state from HTTP: {hex_state}")
        if self.fcu_state.update(hex_state):
            await self.state_changed()

    async def state_changed(self) -> None:
        logger.info(f"[{self.name}] Current state: {self.fcu_state}")
        await self.on_state_changed_callback(self)

    async def periodic_state_reload(self) -> None:
        while True:
            await async_sleep_until_next_multiply_of_minutes(self.STATE_RELOAD_PERIOD_MINUTES)
            try:
                await self.state_reload()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"State reload failed: {e}")
                pass

    async def handle_cmd_hcu_from_estia(self, payload: dict[str, JSONSerializable]) -> None:
        logger.debug(f"Handling Estia HCU command. Payload {payload}")

        if not isinstance(payload["data"], str):
            logger.error(f'[{self.name}] malformed AC state from AMQP: {payload["data"]}')
            return
        logger.debug(f'[{self.name}] AC state from AMQP: {payload["data"]}')

        if self.fcu_state.update(payload["data"]):
            logger.info(f"State updated for device_id: {self.ac_unique_id}")
            await self.state_changed()

    async def handle_cmd_heartbeat_estia(self, payload: dict[str, t.Any]) -> None:
        logger.debug(f"Handling Estia heartbeat command. Payload {payload}")

        try:
            self.temperatures.tfi = int(payload["TFI_temp"], 16)
            self.temperatures.tho = int(payload["THO_temp"], 16)
            self.temperatures.to = int(payload["TO_temp"], 16)
            self.temperatures.twi = int(payload["TWI_temp"], 16)
            self.temperatures.two = int(payload["TWO_temp"], 16)
            self._water_flow_rate = int(payload["FLO"], 16)
        except Exception as e:
            logger.error(f"ERROR CONVERTING DATA: {e}. Payload: '{payload}'")

        await self.state_changed()


    async def handle_update_ac_energy_consumption(self, val: ToshibaAcDeviceEnergyConsumption) -> None:
        if self._ac_energy_consumption != val:
            self._ac_energy_consumption = val

            logger.debug(f"[{self.name}] New energy consumption: {val.energy_wh}Wh")

            await self.on_energy_consumption_changed_callback(self)

    async def send_state_to_ac(self, state: ToshibaAcFcuState) -> None:
        logger.error(f"Sending commands to HP is disabled for the moment")

        # TODO: Disabled on purpose
        #await self.amqp_api.send_message(str(fcu_to_ac))

    @property
    def ac_status(self) -> ToshibaAcStatus:
        return self.fcu_state.ac_status

    async def set_ac_status(self, val: ToshibaAcStatus) -> None:
        state = ToshibaAcFcuState()
        state.ac_status = val

        await self.send_state_to_ac(state)

    @property
    def ac_mode(self) -> ToshibaAcMode:
        return self.fcu_state.ac_mode

    async def set_ac_mode(self, val: ToshibaAcMode) -> None:
        state = ToshibaAcFcuState()
        state.ac_mode = val

        await self.send_state_to_ac(state)

    @property
    def ac_temperature(self) -> t.Optional[int]:
        ret = self.fcu_state.ac_temperature

        return ret


    @property
    def mode(self) -> EstiaWaterMode:
        return self.fcu_state.zone1_mode

    @property
    def ac_indoor_temperature(self) -> t.Optional[int]:
        return self.fcu_state.ac_indoor_temperature

    @property
    def ac_outdoor_temperature(self) -> t.Optional[int]:
        return self.fcu_state.ac_outdoor_temperature

    @property
    def zone1_target_temperature(self) -> t.Optional[int]:
        return self.fcu_state.zone1_target_temperature

    @property
    def dhw_target_temperature(self) -> t.Optional[int]:
        return self.fcu_state.dhw_target_temperature

    @property
    def twi_temperature(self) -> t.Optional[int] | None:
        return ToshibaAcFcuState.EstiaTemperature.from_raw(self.temperatures.twi)

    @property
    def two_temperature(self) -> t.Optional[int] | None:
        return ToshibaAcFcuState.EstiaTemperature.from_raw(self.temperatures.two)

    @property
    def tho_temperature(self) -> t.Optional[int] | None:
        return ToshibaAcFcuState.EstiaTemperature.from_raw(self.temperatures.tho)

    @property
    def to_temperature(self) -> t.Optional[int] | None:
        return ToshibaAcFcuState.EstiaTemperature.from_raw(self.temperatures.to)

    @property
    def tfi_temperature(self) -> t.Optional[int] | None:
        return ToshibaAcFcuState.EstiaTemperature.from_raw(self.temperatures.tfi)

    @property
    def room_water_temperature(self) -> t.Optional[int] | None:
        return ToshibaAcFcuState.EstiaTemperature.from_raw(self.temperatures.room_water)

    @property
    def water_flow_rate(self) -> t.Optional[float]:
        return self._water_flow_rate / 10

    @property
    def water_pump_status(self) -> t.Optional[bool]:
        return self.fcu_state.water_pump_is_running

    @property
    def compressor_status(self) -> t.Optional[EstiaCompressorStatus]:
        return self.fcu_state.compressor_status

    @property
    def electric_coil_dhw_is_active(self) -> t.Optional[bool]:
        return self.fcu_state.electric_coil_dhw_is_active

    @property
    def electric_coil_heat_is_active(self) -> t.Optional[bool]:
        return self.fcu_state.electric_coil_heat_is_active

    @property
    def on_state_changed_callback(self) -> ToshibaAcDeviceCallback:
        return self._on_state_changed_callback

    @property
    def on_energy_consumption_changed_callback(self) -> ToshibaAcDeviceCallback:
        return self._on_energy_consumption_changed_callback
