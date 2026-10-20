"""用户贡献的华为产品 ZF0L（全屋智能 智能中控屏 MINI）适配器。

产品：华为全屋智能 智能中控屏 MINI
厂商：华为
型号：LXB-L40（deviceTypeId A10，中控屏）
Profile：https://smarthome-drcn.dbankcdn.com/device/guide/ZF0L/ZF0L.json

Profile 服务与实体映射
---------------------
  volSwitch.on        bool RW  静音开关      -> 静音（switch）
  micSwitch.on        bool RW  麦克风开关    -> 麦克风（switch）
  undisturbMode.on    bool RW  勿扰模式开关  -> 勿扰模式（switch）
  homeBroadcast.text  string W 家庭广播文本  -> 家庭广播（text，写入即播报）
  netInfo.RSSI        int R    -100~0 dBm    -> Wi-Fi 信号强度（sensor，诊断）

未映射的服务及原因
-----------------
  recoverConfigSwitch.on  还原配置开关。误触会重置面板配置，风险高于价值，
                          不暴露。
  panelMode.extendMode    int RW 0~9999999，没有任何枚举或说明。写入含义不明，
                          按失败关闭原则不暴露。
  roomsleeptime          房间睡眠时间的起止时刻（字符串），属于面板本地作息
                          配置，格式未在 Profile 中说明，不映射。
  undisturbMode.start/end 勿扰的起止时刻。时间窗口语义依赖面板本地时间格式，
                          本版只暴露开关本身。
  deviceInfo / update   插件侧标识与 OTA，运维性质，不映射。

关于家庭广播
-----------
  Profile 把 homeBroadcast 的 text / sessionId / audioId 三个字段都标为可写，
  其中 sessionId 的说明是“广播ID，用于网元问题分析”。本适配器只下发 text
  （一个可读的广播内容）；真机实测表明只带 text 即可正常播报，sessionId
  与 audioId 并非必填。
  该字段写入后不回读，因此实体显示的是最近一次输入的内容。

验证状态
-------
  已在真机（Home Assistant 2026.10.1 / 集成 2026.10.16）实测：静音、麦克风、勿扰的回读与写入均与设备
  实际一致，家庭广播按只下发 text 的方式验证通过。三个开关按 bool 类型
  下发 0/1。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_VOLUME_SID = "volSwitch"
_MIC_SID = "micSwitch"
_UNDISTURB_SID = "undisturbMode"
_BROADCAST_SID = "homeBroadcast"
_NET_INFO_SID = "netInfo"

# 面板文本长度上限，与 text 平台的实际渲染上限一致。
_BROADCAST_MAX_LENGTH = 255


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


def _switch_spec(
    context: DeviceContext,
    sid: str,
    key: str,
    name: str,
    *,
    entity_category: str | None = None,
) -> EntitySpec | None:
    field = _field(context.profile, sid, "on")
    if field is None or not _is_writable(field):
        return None

    def state(device: DeviceContext) -> Mapping[str, Any]:
        return {"is_on": _bool(device.value(sid, "on"))}

    async def _set(device: DeviceContext, enabled: bool) -> None:
        await device.async_send_service(
            sid, {"on": _coerce(1 if enabled else 0, field)}
        )

    async def turn_on(
        device: DeviceContext, _data: Mapping[str, Any]
    ) -> None:
        await _set(device, True)

    async def turn_off(
        device: DeviceContext, _data: Mapping[str, Any]
    ) -> None:
        await _set(device, False)

    metadata: dict[str, Any] = {}
    if entity_category is not None:
        metadata["entity_category"] = entity_category

    return EntitySpec(
        platform="switch",
        key=key,
        name=name,
        state=state,
        metadata=metadata,
        actions={"turn_on": turn_on, "turn_off": turn_off},
    )


class ProductZF0LAdapter:
    """把 ZF0L 的实体与控制命令全部约束在本文件内。"""

    prod_id = "ZF0L"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()

        entities: list[EntitySpec] = []
        for sid, key, name in (
            (_VOLUME_SID, "mute", "静音"),
            (_MIC_SID, "microphone", "麦克风"),
            (_UNDISTURB_SID, "do_not_disturb", "勿扰模式"),
        ):
            if not context.has_service(sid):
                continue
            spec = _switch_spec(context, sid, key, name)
            if spec is not None:
                entities.append(spec)

        # --- 家庭广播 -------------------------------------------------
        text_field = _field(profile, _BROADCAST_SID, "text")
        if context.has_service(_BROADCAST_SID) and _is_writable(text_field):
            async def set_broadcast(
                device: DeviceContext, data: Mapping[str, Any]
            ) -> None:
                value = data.get("value")
                if not isinstance(value, str) or not value.strip():
                    raise ValueError("广播内容不能为空")
                await device.async_send_service(
                    _BROADCAST_SID,
                    {"text": value.strip()[:_BROADCAST_MAX_LENGTH]},
                )

            entities.append(
                EntitySpec(
                    platform="text",
                    key="broadcast",
                    name="家庭广播",
                    state=lambda device: {},
                    metadata={"max": _BROADCAST_MAX_LENGTH},
                    actions={"set_value": set_broadcast},
                )
            )

        # --- 网络诊断 -------------------------------------------------
        if context.has_service(_NET_INFO_SID):
            def rssi_state(device: DeviceContext) -> Mapping[str, Any]:
                return {"native_value": _int(device.value(_NET_INFO_SID, "RSSI"))}

            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="wifi_rssi",
                    name="Wi-Fi 信号强度",
                    state=rssi_state,
                    metadata={
                        "unit": "dBm",
                        "device_class": "signal_strength",
                        "state_class": "measurement",
                        "entity_category": "diagnostic",
                    },
                )
            )

        return tuple(entities)


ADAPTER = ProductZF0LAdapter()
