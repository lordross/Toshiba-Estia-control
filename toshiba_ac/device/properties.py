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


from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto


@dataclass
class ToshibaAcDeviceEnergyConsumption:
    energy_wh: float
    since: datetime


class ToshibaAcStatus(Enum):
    ON = auto()
    OFF = auto()
    NONE = None


class EstiaCompressorStatus(Enum):
    OFF = auto()
    DHW = auto()
    HEAT = auto()
    NONE = None

class EstiaWaterMode(Enum):
    AUTO = auto()
    COOL = auto()
    HEAT = auto()
    NONE = None

class ToshibaAcMode(Enum):
    AUTO = auto()
    COOL = auto()
    HEAT = auto()
    NONE = None
