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

import asyncio
import logging
import typing as t

from toshiba_estia.device import ToshibaAcDevice
from toshiba_estia.utils import async_sleep_until_next_multiply_of_minutes, ToshibaAcCallback
from toshiba_estia.utils.amqp_api import ToshibaAcAmqpApi, JSONSerializable
from toshiba_estia.utils.http_api import ToshibaAcHttpApi, ToshibaDevicesCount, ToshibaDeviceConnectionState

logger = logging.getLogger(__name__)


class ToshibaAcDeviceManagerError(Exception):
    pass


class ToshibaAcSasTokenUpdatedCallback(ToshibaAcCallback[str]):
    pass


class ToshibaAcDeviceManager:
    FETCH_ENERGY_CONSUMPTION_PERIOD_MINUTES = 60
    FETCH_DEVICE_STATUS_PERIOD_MINUTES = 60

    def __init__(
        self,
        username: str,
        password: str,
        device_id: t.Optional[str] = None,
        sas_token: t.Optional[str] = None,
    ):
        self.username = username
        self.password = password
        self.http_api: t.Optional[ToshibaAcHttpApi] = None
        self.reg_info = None
        self.amqp_api: t.Optional[ToshibaAcAmqpApi] = None
        self.device_id = self.username + "_" + (device_id or "3e6e4eb5f0e5aa46")
        self.sas_token = sas_token
        self.devices: t.Dict[str, ToshibaAcDevice] = {}
        self.periodic_fetch_energy_consumption_task: t.Optional[asyncio.Task[None]] = None
        self.periodic_fetch_device_connection_task: t.Optional[asyncio.Task[None]] = None
        self.lock = asyncio.Lock()
        self.loop = asyncio.get_running_loop()
        self._on_sas_token_updated_callback = ToshibaAcSasTokenUpdatedCallback()

    async def connect(self) -> str:
        try:
            async with self.lock:
                if not self.http_api:
                    self.http_api = ToshibaAcHttpApi(self.username, self.password)
                    await self.http_api.connect()

                if not self.sas_token:
                    self.sas_token = await self.http_api.register_client(self.device_id)

                if not self.amqp_api:
                    self.amqp_api = ToshibaAcAmqpApi(self.sas_token, self.renew_sas_token)
                    self.amqp_api.register_command_handler("CMD_HEARTBEAT_ESTIA", self.handle_cmd_heartbeat_estia)
                    self.amqp_api.register_command_handler("CMD_HDU_FROM_ESTIA", self.handle_cmd_hcu_from_estia)

                    await self.amqp_api.connect()

                return self.sas_token

        except:
            await self.shutdown()
            raise

    async def shutdown(self) -> None:
        async with self.lock:
            tasks: t.List[t.Awaitable[None]] = []

            if self.periodic_fetch_device_connection_task:
                self.periodic_fetch_device_connection_task.cancel()
                tasks.append(self.periodic_fetch_device_connection_task)

            if self.periodic_fetch_energy_consumption_task:
                self.periodic_fetch_energy_consumption_task.cancel()
                tasks.append(self.periodic_fetch_energy_consumption_task)



            tasks.extend(device.shutdown() for device in self.devices.values())

            if self.amqp_api:
                tasks.append(self.amqp_api.shutdown())

            if self.http_api:
                tasks.append(self.http_api.shutdown())

            try:
                if tasks:
                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    def raise_all_errors(res: t.Any, *args: t.Any) -> None:
                        try:
                            if isinstance(res, Exception):
                                raise res
                        finally:
                            if args:
                                raise_all_errors(*args)

                    raise_all_errors(*results)
            finally:
                self.periodic_fetch_device_connection_task = None
                self.periodic_fetch_energy_consumption_task = None
                self.amqp_api = None
                self.http_api = None

    async def periodic_fetch_energy_consumption(self) -> None:
        while True:
            await async_sleep_until_next_multiply_of_minutes(self.FETCH_ENERGY_CONSUMPTION_PERIOD_MINUTES)
            try:
                await self.fetch_energy_consumption()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Fetching energy consumption failed: {e}")
                pass

    async def fetch_energy_consumption(self) -> None:
        if not self.http_api:
            raise ToshibaAcDeviceManagerError("Not connected")

        consumptions = await self.http_api.get_devices_energy_consumption(
            [ac_unique_id for ac_unique_id in self.devices.keys()]
        )

        logger.debug(
            "Power consumption for devices: {"
            + " ,".join(
                f"{self.devices[ac_unique_id].name}: {consumption.energy_wh}Wh"
                for ac_unique_id, consumption in consumptions.items()
            )
            + "}"
        )

        updates = []

        for ac_unique_id, consumption in consumptions.items():
            update = self.devices[ac_unique_id].handle_update_ac_energy_consumption(consumption)
            updates.append(update)

        await asyncio.gather(*updates)

    async def periodic_fetch_device_connection(self) -> None:
        while True:
            await async_sleep_until_next_multiply_of_minutes(self.FETCH_DEVICE_STATUS_PERIOD_MINUTES)
            try:
                await self.fetch_device_status()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Fetching device status failed: {e}")
                pass

    async def fetch_device_status(self) -> None:
        if not self.http_api:
            raise ToshibaAcDeviceManagerError("Not connected")

        devices_connection_status = await self.http_api.get_device_connection_state(
            [ac_unique_id for ac_unique_id in self.devices.keys()]
        )

        logger.debug(
            "Connection status for devices: {"
            + " ,".join(
                f"{self.devices[ac_unique_id].name}: {connection_status.online}"
                for ac_unique_id, connection_status in devices_connection_status.items()
            )
            + "}"
        )

        updates = []

        for ac_unique_id, connection_status in devices_connection_status.items():
            logger.debug(f"Notify device_id={ac_unique_id} for connection status {connection_status.online}")
            update = self.devices[ac_unique_id].handle_connection_state(connection_status.online)
            updates.append(update)

        await asyncio.gather(*updates)


    async def get_devices(self) -> t.List[ToshibaAcDevice]:
        if not self.http_api or not self.amqp_api:
            raise ToshibaAcDeviceManagerError("Not connected")

        async with self.lock:
            if not self.devices:
                devices_info = await self.http_api.get_devices()

                logger.debug(
                    "Found devices: {"
                    + " ,".join(
                        f"{device.ac_name}: {{MeritFeature: {device.merit_feature}, "
                        + f"Model id: {device.ac_model_id}, "
                        + f"Firmware version: {device.firmware_version}, "
                        + f"Initial state: {device.initial_ac_state}}}"
                        for device in devices_info
                    )
                )

                connects = []

                for device_info in devices_info:
                    device = ToshibaAcDevice(
                        device_info.ac_name,
                        self.device_id,
                        device_info.ac_id,
                        device_info.ac_unique_id,
                        device_info.initial_ac_state,
                        device_info.firmware_version,
                        device_info.merit_feature,
                        device_info.ac_model_id,
                        self.amqp_api,
                        self.http_api,
                    )

                    connects.append(device.connect())

                    logger.debug(f"Adding device {device.name}")

                    self.devices[device.ac_unique_id] = device

                await asyncio.gather(*connects)

                await self.fetch_energy_consumption()

                if not self.periodic_fetch_energy_consumption_task:
                    self.periodic_fetch_energy_consumption_task = asyncio.get_running_loop().create_task(
                        self.periodic_fetch_energy_consumption()
                    )

                if not self.periodic_fetch_device_connection_task:
                    self.periodic_fetch_device_connection_task = asyncio.get_running_loop().create_task(
                        self.periodic_fetch_device_connection()
                    )

            return list(self.devices.values())


    async def get_devices_count(self) -> ToshibaDevicesCount:
        if not self.http_api or not self.amqp_api:
            raise ToshibaAcDeviceManagerError("Not connected")

        devices_count = await self.http_api.get_devices_count()
        return devices_count

    async def get_device_connection_state(self, device_ids: t.List[str]) -> t.List[ToshibaDeviceConnectionState]:
        if not self.http_api:
            raise ToshibaAcDeviceManagerError("Not connected")

        connection_states = await self.http_api.get_device_connection_state(device_ids)
        return connection_states

    async def renew_sas_token(self) -> str:
        if self.http_api:
            self.sas_token = await self.http_api.register_client(self.device_id)
            await self.on_sas_token_updated_callback(self.sas_token)
            return self.sas_token

        raise ToshibaAcDeviceManagerError("Not connected")

    def handle_cmd_heartbeat_estia(
        self,
        source_id: str,
        message_id: str,
        target_id: list[JSONSerializable],
        payload: dict[str, JSONSerializable],
        timestamp: str,
    ) -> None:
        asyncio.run_coroutine_threadsafe(self.devices[source_id].handle_cmd_heartbeat_estia(payload), self.loop).result()

    def handle_cmd_hcu_from_estia(
        self,
        source_id: str,
        message_id: str,
        target_id: list[JSONSerializable],
        payload: dict[str, JSONSerializable],
        timestamp: str,
    ) -> None:
        asyncio.run_coroutine_threadsafe(self.devices[source_id].handle_cmd_hcu_from_estia(payload), self.loop).result()

    @property
    def on_sas_token_updated_callback(self) -> ToshibaAcSasTokenUpdatedCallback:
        return self._on_sas_token_updated_callback
