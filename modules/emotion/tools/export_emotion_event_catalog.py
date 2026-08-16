#!/usr/bin/env python3
"""从情绪配置生成事件映射目录，避免手工复制事件表。"""

from __future__ import annotations

import argparse
import csv
import io
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    # 支持直接执行 tools/ 下的脚本，不依赖调用方预先设置 PYTHONPATH。
    sys.path.insert(0, str(PROJECT_ROOT))

from marsdog_core.config_loader import LoadConfig  # noqa: E402


DEFAULT_MARKDOWN_OUTPUT = PROJECT_ROOT / "docs" / "emotion_event_catalog.md"
DEFAULT_CSV_OUTPUT = PROJECT_ROOT / "docs" / "emotion_event_catalog.csv"


def GetEmotionEventGroupValue(eventName: str) -> str:
    """根据事件名前缀返回输入类别。"""
    if eventName.startswith(("EVT_AUDIO_", "EVT_VOICE_")):
        return "声音输入"
    if eventName.startswith("EVT_TACTILE_"):
        return "触摸输入"
    if eventName.startswith("EVT_VISION_"):
        return "视觉输入"
    return "其他输入"


def BuildEmotionDeltaTextValue(
    deltas: dict[str, Any],
    emotionTypes: dict[str, Any],
) -> str:
    """把情绪基础增量转换为便于文档和表格阅读的文本。"""
    parts: list[str] = []
    for emotionName, delta in deltas.items():
        emotionConfig = emotionTypes.get(emotionName, {})
        chineseName = str(emotionConfig.get("chineseName", emotionName))
        numericDelta = float(delta)
        formattedDelta = f"{numericDelta:+g}"
        parts.append(f"{chineseName}（{emotionName}）{formattedDelta}")
    return "、".join(parts)


def BuildMetadataMultiplierTextValue(rules: list[dict[str, Any]]) -> str:
    """把可选元数据倍率规则转换为稳定文本。"""
    parts: list[str] = []
    for rule in rules:
        key = str(rule.get("key", ""))
        operator = str(rule.get("operator", "truthy"))
        valueText = "" if operator == "truthy" else f" {rule.get('value')}"
        parts.append(
            f"{key} {operator}{valueText} ×{float(rule.get('multiplier', 1.0)):g}"
        )
    return "；".join(parts) if parts else "无"


def GetEmotionEventCatalogRowsValue(
    emotionConfig: dict[str, Any],
) -> list[dict[str, str]]:
    """从情绪配置提取按原始配置顺序排列的事件目录行。"""
    emotionTypes = emotionConfig.get("types", {})
    eventRules = emotionConfig.get("eventRules", {})
    rows: list[dict[str, str]] = []
    for eventName, mapping in eventRules.items():
        rows.append(
            {
                "input_type": GetEmotionEventGroupValue(str(eventName)),
                "event_type": str(eventName),
                "base_emotion_deltas": BuildEmotionDeltaTextValue(
                    mapping.get("deltas", {}),
                    emotionTypes,
                ),
                "metadata_multipliers": BuildMetadataMultiplierTextValue(
                    mapping.get("metadataMultipliers", []),
                ),
            }
        )
    return rows


def BuildEmotionEventCatalogMarkdownValue(emotionConfig: dict[str, Any]) -> str:
    """生成可提交并由测试校验的 Markdown 情绪事件目录。"""
    rows = GetEmotionEventCatalogRowsValue(emotionConfig)
    deduplicationWindowSeconds = float(
        emotionConfig.get("eventDeduplicationWindowSeconds", 10)
    )
    lines = [
        "# 情绪事件映射目录",
        "",
        "<!-- 此文件由 tools/export_emotion_event_catalog.py 自动生成，请勿手工修改。 -->",
        "",
        "本目录的唯一数据来源是 `configs/emotions.yaml:eventRules`。基础增量会继续乘以",
        "当前性格系数，最终情绪值限制在 `0-100`；只有下表明确列出的规则才使用元数据倍率。",
        f"同名外部事件在 `{deduplicationWindowSeconds:g}` 秒内只计算一次，不同事件互不影响。",
        "",
    ]
    groupNames = ("声音输入", "触摸输入", "视觉输入", "其他输入")
    for groupName in groupNames:
        groupRows = [row for row in rows if row["input_type"] == groupName]
        if not groupRows:
            continue
        lines.extend(
            [
                f"## {groupName}",
                "",
                "| event_type | 固定基础情绪增量 | 元数据倍率 |",
                "|---|---|---|",
            ]
        )
        for row in groupRows:
            lines.append(
                "| `{event_type}` | {base_emotion_deltas} | {metadata_multipliers} |".format(
                    **row
                )
            )
        lines.append("")
    return "\n".join(lines)


def BuildEmotionEventCatalogCsvValue(emotionConfig: dict[str, Any]) -> str:
    """生成可直接用 Excel 打开的 UTF-8 CSV 情绪事件目录。"""
    output = io.StringIO(newline="")
    fieldNames = (
        "input_type",
        "event_type",
        "base_emotion_deltas",
        "metadata_multipliers",
    )
    writer = csv.DictWriter(output, fieldnames=fieldNames)
    writer.writeheader()
    writer.writerows(GetEmotionEventCatalogRowsValue(emotionConfig))
    return output.getvalue()


def GetOutputTextValue(outputFormat: str, emotionConfig: dict[str, Any]) -> str:
    """根据命令行格式选择对应的目录文本。"""
    if outputFormat == "markdown":
        return BuildEmotionEventCatalogMarkdownValue(emotionConfig)
    if outputFormat == "csv":
        return BuildEmotionEventCatalogCsvValue(emotionConfig)
    raise ValueError(f"Unsupported output format: {outputFormat}")


def ParseArgumentsValue() -> argparse.Namespace:
    """解析事件目录生成工具的命令行参数。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--format",
        choices=("markdown", "csv"),
        default="markdown",
        dest="outputFormat",
        help="输出 Markdown 或可由 Excel 打开的 CSV。",
    )
    parser.add_argument("--output", type=Path, help="覆盖默认输出路径。")
    parser.add_argument(
        "--check",
        action="store_true",
        help="只检查目标文件是否与当前配置一致。",
    )
    return parser.parse_args()


def main() -> int:
    """生成目录文件，或在检查模式验证目录没有过期。"""
    arguments = ParseArgumentsValue()
    emotionConfig = LoadConfig("emotions", PROJECT_ROOT / "configs").get(
        "emotions",
        {},
    )
    outputText = GetOutputTextValue(arguments.outputFormat, emotionConfig)
    defaultOutput = (
        DEFAULT_MARKDOWN_OUTPUT
        if arguments.outputFormat == "markdown"
        else DEFAULT_CSV_OUTPUT
    )
    outputPath = arguments.output or defaultOutput

    if arguments.check:
        currentText = (
            outputPath.read_text(encoding="utf-8")
            if outputPath.exists()
            else None
        )
        if currentText != outputText:
            print(f"情绪事件目录需要重新生成：{outputPath}")
            return 1
        print(f"情绪事件目录与配置一致：{outputPath}")
        return 0

    outputPath.parent.mkdir(parents=True, exist_ok=True)
    outputPath.write_text(outputText, encoding="utf-8")
    print(f"已生成情绪事件目录：{outputPath}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
