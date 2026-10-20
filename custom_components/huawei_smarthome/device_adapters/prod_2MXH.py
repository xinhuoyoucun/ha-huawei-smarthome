"""用户贡献的华为产品 2MXH（吸顶式红外人体移动光照传感器）适配器。

产品：吸顶式红外人体移动光照传感器
厂商：麦乐克（MIR-IR01-PLC）
deviceTypeId：049
Profile：https://smarthome-drcn.dbankcdn.com/device/guide/2MXH/2MXH.json

Profile 服务与实体映射
---------------------
  pir.status                   enum R   0=无人 1=有人 -> 有人（binary_sensor，动效检测）
  luminance.current            int  R   0~5000     -> 照度（sensor，单位 lx）
  luminance.threshold          int  RW  1~100 %    -> 光照变化阈值（number）
  delayTime.time               int  RW  5~480 s    -> 延时时间（number）
  switchNightLight.on          bool RW  0=关 1=开  -> 感应上报（switch）
                               Profile 的服务类型是 switch，中文说明是“感应上报”，
                               故实体按“感应上报”命名，而不是当作小夜灯。
  commonFaultDetection.status  bool R  0=正常 1=异常 -> 故障（binary_sensor）
  luminanceReportSetting.interval int RW 10~65535 s -> 光照上报间隔（number，诊断）
  netInfo                      R                    -> 不映射（网络信息，无常驻价值）

未映射的服务及原因
-----------------
  luminance.level         光照等级（微光/弱光/正常光/强光）与照度是同一能力的
                          两种表达，属于重复投影，只保留照度。
  selfCheck.on            自检启动，是一次性动作且没有结果回报，不暴露。
  configureSwitch1.on     中文说明只有“参数配置”，无法判断具体语义，按失败关闭
                          原则不暴露。
  update                   OTA 运维字段，不映射。

验证状态
-------
  已在真机（Home Assistant 2026.10.1 / 集成 2026.10.16）实测：有人、照度、故障的回读，以及阈值、延时
  时间、感应上报、上报间隔的写入均与设备实际一致；写入值按 Profile 的
  特征类型做数值化。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_FAULT_SID = "commonFaultDetection"
_LUMINANCE_SID = "luminance"
_PIR_SID = "pir"
_REPORT_SID = "luminanceReportSetting"
_DELAY_SID = "delayTime"
_SWITCH_SID = "switchNightLight"


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


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.casefold() in {"1", "true", "on"}:
            return True
        if value.casefold() in {"0", "false", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return None


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
    """按 Profile 声明的特征类型把命令值数值化（真机只接受数值）。"""

    if not isinstance(field, Mapping):
        return value
    data_type = str(field.get("characteristicType") or "").casefold()
    if data_type in {"bool", "int", "integer", "enum"}:
        number = _number(value)
        if number is None:
            return value
        return int(number) if number.is_integer() else number
    return value


def _enum_label(
    field: Mapping[str, Any] | None,
    value: Any,
) -> str | None:
    if not isinstance(field, Mapping) or value is None:
        return None
    for option in field.get("enumList", ()):
        if not isinstance(option, Mapping):
            continue
        if str(option.get("enumVal")) != str(value):
            continue
        label = option.get("descCh") or option.get("descEn")
        if isinstance(label, str) and label.strip():
            return label.strip()
    return None


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
    return _coerce(number, field)


def _number_spec(
    context: DeviceContext,
    sid: str,
    field_name: str,
    key: str,
    name: str,
    *,
    unit: str | None = None,
    entity_category: str | None = None,
) -> EntitySpec | None:
    """按 Profile 的字段声明生成一个可写数值实体。"""

    field = _field(context.profile, sid, field_name)
    if field is None or not _is_writable(field):
        return None
    minimum = _number(field.get("min"))
    maximum = _number(field.get("max"))
    if minimum is None or maximum is None:
        return None
    step = _number(field.get("step"))

    def state(device: DeviceContext) -> Mapping[str, Any]:
        return {"native_value": _number(device.value(sid, field_name))}

    async def set_value(
        device: DeviceContext, data: Mapping[str, Any]
    ) -> None:
        value = _clamp(data.get("value"), field)
        if value is None:
            raise ValueError(f"{name} is required")
        await device.async_send_service(sid, {field_name: value})

    metadata: dict[str, Any] = {
        "min": minimum,
        "max": maximum,
        "step": step if step and step > 0 else 1,
    }
    if unit is not None:
        metadata["unit"] = unit
    if entity_category is not None:
        metadata["entity_category"] = entity_category

    return EntitySpec(
        platform="number",
        key=key,
        name=name,
        state=state,
        metadata=metadata,
        actions={"set_value": set_value},
    )


class Product2MXHAdapter:
    """把 2MXH 的实体与控制命令全部约束在本文件内。"""

    prod_id = "2MXH"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None or not context.has_service(_PIR_SID):
            return ()

        entities: list[EntitySpec] = []

        # --- 有人 / 无人 ----------------------------------------------
        def pir_state(device: DeviceContext) -> Mapping[str, Any]:
            return {"is_on": _int(device.value(_PIR_SID, "status")) == 1}

        entities.append(
            EntitySpec(
                platform="binary_sensor",
                key="presence",
                name="有人",
                state=pir_state,
                metadata={"device_class": "motion"},
            )
        )

        # --- 照度 -----------------------------------------------------
        if context.has_service(_LUMINANCE_SID):
            def illuminance_state(device: DeviceContext) -> Mapping[str, Any]:
                return {
                    "native_value": _number(
                        device.value(_LUMINANCE_SID, "current")
                    )
                }

            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="illuminance",
                    name="照度",
                    state=illuminance_state,
                    metadata={
                        "unit": "lx",
                        "device_class": "illuminance",
                        "state_class": "measurement",
                    },
                )
            )

            threshold = _number_spec(
                context,
                _LUMINANCE_SID,
                "threshold",
                "luminance_threshold",
                "光照变化阈值",
                unit="%",
                entity_category="config",
            )
            if threshold is not None:
                entities.append(threshold)

        # --- 延时时间 -------------------------------------------------
        delay = _number_spec(
            context,
            _DELAY_SID,
            "time",
            "delay_time",
            "延时时间",
            unit="s",
            entity_category="config",
        )
        if delay is not None:
            entities.append(delay)

        # --- 光照上报间隔（诊断） -------------------------------------
        interval = _number_spec(
            context,
            _REPORT_SID,
            "interval",
            "luminance_interval",
            "光照上报间隔",
            unit="s",
            entity_category="diagnostic",
        )
        if interval is not None:
            entities.append(interval)

        # --- 感应上报 -------------------------------------------------
        report_field = _field(profile, _SWITCH_SID, "on")
        if context.has_service(_SWITCH_SID) and _is_writable(report_field):
            def report_state(device: DeviceContext) -> Mapping[str, Any]:
                return {"is_on": _bool(device.value(_SWITCH_SID, "on"))}

            async def _set_report(
                device: DeviceContext, enabled: bool
            ) -> None:
                await device.async_send_service(
                    _SWITCH_SID,
                    {"on": _coerce(1 if enabled else 0, report_field)},
                )

            async def turn_on(
                device: DeviceContext, _data: Mapping[str, Any]
            ) -> None:
                await _set_report(device, True)

            async def turn_off(
                device: DeviceContext, _data: Mapping[str, Any]
            ) -> None:
                await _set_report(device, False)

            entities.append(
                EntitySpec(
                    platform="switch",
                    key="presence_report",
                    name="感应上报",
                    state=report_state,
                    actions={"turn_on": turn_on, "turn_off": turn_off},
                )
            )

        # --- 故障 -----------------------------------------------------
        if context.has_service(_FAULT_SID):
            code_field = _field(profile, _FAULT_SID, "code")

            def fault_state(device: DeviceContext) -> Mapping[str, Any]:
                status = _bool(device.value(_FAULT_SID, "status"))
                code = _int(device.value(_FAULT_SID, "code"))
                is_on = status if status is not None else (
                    None if code is None else code != 0
                )
                attributes: dict[str, Any] = {}
                if code is not None:
                    attributes["fault_code"] = code
                    label = _enum_label(code_field, code)
                    if label is not None and code != 0:
                        attributes["fault_description"] = label
                return {
                    "is_on": is_on,
                    "extra_state_attributes": attributes or None,
                }

            entities.append(
                EntitySpec(
                    platform="binary_sensor",
                    key="problem",
                    name="故障",
                    state=fault_state,
                    metadata={"device_class": "problem"},
                )
            )

        return tuple(entities)


ADAPTER = Product2MXHAdapter()
