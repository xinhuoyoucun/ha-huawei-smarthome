"""用户贡献的华为产品 ZG1P（全屋智能调光驱动器 2 路 双色温 恒压 100W）适配器。

产品：华为全屋智能 调光驱动器 2路 双色温 恒压 100W
厂商：华为
型号：BER-LD01（deviceTypeId A0E）
Profile：https://smarthome-drcn.dbankcdn.com/device/guide/ZG1P/ZG1P.json

Profile 服务与实体映射
---------------------
  第 1 路：switch1.on / brightness1.brightness / cct1.colorTemperature
  第 2 路：switch2.on / brightness2.brightness / cct2.colorTemperature
  两路各自独立成 light 实体，命名为“回路 1”“回路 2”。

  brightness     int  RW  0~100 %     -> HA 的 0~255（按比例换算，不硬编码）
  colorTemperature int RW 2000~6500 K -> HA 的 color_temp_kelvin，范围取自 Profile

未映射的服务及原因
-----------------
  relBrightness1/2   相对调光（-100~100）与旋转调光状态，属于面板侧的一过性
                     操作，没有可读的最终值，按失败关闭原则不暴露。
  fadeTime1/2、fadeTimeSetting1/2   渐变时间，属于调光曲线调参，日常价值低。
  memorySwitch       断电记忆开关，配置项。
  lightCurveSetting1/2  调光曲线（线性/指数/对数），配置项。
  outputMask、powerCon  出厂/工程参数，普通用户无需改动。
  faultDetection     故障检测，读字段与写字段混在同一服务，语义需真机确认，
                     本版不映射。

验证状态
-------
  已在真机（Home Assistant 2026.10.1 / 集成 2026.10.16）实测：两路的开关、亮度、色温回读与写入均与设备
  实际一致；亮度按 0~100 的比例换算到 HA 的 0~255。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_BRIGHTNESS_MAX = 100
_HA_BRIGHTNESS_MAX = 255


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    number = _number(value)
    return None if number is None else int(round(number))


def _field(
    profile: Mapping[str, Any] | None,
    sid: str,
    name: str,
) -> Mapping[str, Any] | None:
    if not isinstance(profile, Mapping):
        return None
    for service in profile.get("services", ()):
        if not isinstance(service, Mapping) or service.get("serviceId") != sid:
            continue
        for field in service.get("characteristics", ()):
            if (
                isinstance(field, Mapping)
                and field.get("characteristicName") == name
            ):
                return field
        return None
    return None


def _is_writable(field: Mapping[str, Any] | None) -> bool:
    if not isinstance(field, Mapping):
        return False
    return "W" in str(field.get("method") or "")


def _coerce(value: Any, field: Mapping[str, Any] | None) -> Any:
    """按 Profile 声明的特征类型把命令值数值化。"""

    if not isinstance(field, Mapping):
        return value
    data_type = str(field.get("characteristicType") or "").casefold()
    if data_type in {"bool", "int", "integer", "enum"}:
        number = _number(value)
        if number is None:
            return value
        return int(number) if number.is_integer() else number
    return value


def _clamp(value: Any, field: Mapping[str, Any] | None) -> Any:
    number = _number(value)
    if number is None:
        return None
    minimum = _number((field or {}).get("min"))
    maximum = _number((field or {}).get("max"))
    if minimum is not None:
        number = max(number, minimum)
    if maximum is not None:
        number = min(number, maximum)
    step = _number((field or {}).get("step"))
    if step and step > 0 and minimum is not None:
        number = minimum + round((number - minimum) / step) * step
        if maximum is not None:
            number = min(number, maximum)
    return _coerce(int(round(number)), field)


def _switch_on(value: Any) -> bool | None:
    number = _number(value)
    if number is not None:
        return number != 0
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.casefold() in {"1", "true", "on"}:
            return True
        if value.casefold() in {"0", "false", "off"}:
            return False
    return None


def _device_to_ha_brightness(value: Any) -> int | None:
    number = _number(value)
    if number is None:
        return None
    number = min(max(number, 0), _BRIGHTNESS_MAX)
    return round(number * _HA_BRIGHTNESS_MAX / _BRIGHTNESS_MAX)


def _ha_to_device_brightness(value: Any) -> int | None:
    number = _number(value)
    if number is None:
        return None
    number = min(max(number, 0), _HA_BRIGHTNESS_MAX)
    return max(1, round(number * _BRIGHTNESS_MAX / _HA_BRIGHTNESS_MAX))


class _Channel:
    """一轮回路的服务名与 Profile 字段，逐路硬编码。"""

    def __init__(
        self,
        switch_sid: str,
        brightness_sid: str,
        cct_sid: str,
    ) -> None:
        self.switch_sid = switch_sid
        self.brightness_sid = brightness_sid
        self.cct_sid = cct_sid


_CHANNELS = (
    ("light_1", "回路 1", _Channel("switch1", "brightness1", "cct1")),
    ("light_2", "回路 2", _Channel("switch2", "brightness2", "cct2")),
)


class ProductZG1PAdapter:
    """把 ZG1P 的实体与控制命令全部约束在本文件内。"""

    prod_id = "ZG1P"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None or not context.has_service("switch1"):
            return ()

        entities: list[EntitySpec] = []
        for key, name, channel in _CHANNELS:
            spec = self._light_spec(context, key, name, channel)
            if spec is not None:
                entities.append(spec)
        return tuple(entities)

    def _light_spec(
        self,
        context: DeviceContext,
        key: str,
        name: str,
        channel: _Channel,
    ) -> EntitySpec | None:
        if not context.has_service(channel.switch_sid):
            return None
        switch_field = _field(context.profile, channel.switch_sid, "on")
        brightness_field = _field(
            context.profile, channel.brightness_sid, "brightness"
        )
        cct_field = _field(
            context.profile, channel.cct_sid, "colorTemperature"
        )
        if (
            switch_field is None
            or brightness_field is None
            or cct_field is None
            or not _is_writable(switch_field)
            or not _is_writable(brightness_field)
            or not _is_writable(cct_field)
        ):
            return None

        def state(device: DeviceContext) -> Mapping[str, Any]:
            return {
                "is_on": _switch_on(device.value(channel.switch_sid, "on")),
                "brightness": _device_to_ha_brightness(
                    device.value(channel.brightness_sid, "brightness")
                ),
                "color_temp_kelvin": _int(
                    device.value(channel.cct_sid, "colorTemperature")
                ),
                "color_mode": "color_temp",
            }

        async def _send_switch(
            device: DeviceContext, value: int
        ) -> None:
            await device.async_send_service(
                channel.switch_sid,
                {"on": _coerce(value, switch_field)},
            )

        async def turn_on(
            device: DeviceContext, data: Mapping[str, Any]
        ) -> None:
            if data.get("rgb_color") is not None:
                raise ValueError("ZG1P Profile 只支持色温，不支持 RGB")
            brightness = data.get("brightness")
            temperature = data.get("color_temp_kelvin")

            brightness_command = None
            if brightness is not None:
                amount = _number(brightness)
                if amount is None or not 0 <= amount <= _HA_BRIGHTNESS_MAX:
                    raise ValueError("无效的亮度值")
                if amount == 0:
                    # 亮度为 0 等价于关灯，和 ZG17 的做法一致。
                    await _send_switch(device, 0)
                    return
                brightness_command = _ha_to_device_brightness(amount)

            temperature_command = None
            if temperature is not None:
                temperature_command = _clamp(temperature, cct_field)
                if temperature_command is None:
                    raise ValueError("无效的色温值")

            await _send_switch(device, 1)
            if brightness_command is not None:
                await device.async_send_service(
                    channel.brightness_sid,
                    {"brightness": _clamp(brightness_command, brightness_field)},
                )
            if temperature_command is not None:
                await device.async_send_service(
                    channel.cct_sid,
                    {"colorTemperature": temperature_command},
                )

        async def turn_off(
            device: DeviceContext, _data: Mapping[str, Any]
        ) -> None:
            await _send_switch(device, 0)

        cct_min = _number(cct_field.get("min"))
        cct_max = _number(cct_field.get("max"))
        metadata: dict[str, Any] = {"supported_color_modes": {"color_temp"}}
        if cct_min is not None:
            metadata["min_color_temp_kelvin"] = int(cct_min)
        if cct_max is not None:
            metadata["max_color_temp_kelvin"] = int(cct_max)

        return EntitySpec(
            platform="light",
            key=key,
            name=name,
            state=state,
            metadata=metadata,
            actions={"turn_on": turn_on, "turn_off": turn_off},
        )


ADAPTER = ProductZG1PAdapter()
