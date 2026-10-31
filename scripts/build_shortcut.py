#!/usr/bin/env python3
"""Build and sign the "Send to Frame TV" Apple Shortcut.

Signing goes through Apple, so it needs a Mac signed in to iCloud; --no-sign skips
it. A signed shortcut can be AirDropped or attached to a GitHub release. See
docs/apple-shortcut.md.
"""
import argparse
import plistlib
import shlex
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

NAME = "Send to Frame TV"  # Shortcuts names an imported shortcut after its file
DEFAULT_URL = "http://artbuff.jaybuff.com/api/send-image"
CONDITION_HAS_ANY_VALUE = 100


def _uuid() -> str:
    return str(uuid.uuid4()).upper()


def _output(uid: str, name: str) -> dict:
    return {"OutputUUID": uid, "OutputName": name, "Type": "ActionOutput"}


def _attachment(value: dict) -> dict:
    return {"Value": value, "WFSerializationType": "WFTextTokenAttachment"}


def _text_with(value: dict) -> dict:
    return {
        "Value": {"string": "￼", "attachmentsByRange": {"{0, 1}": value}},
        "WFSerializationType": "WFTextTokenString",
    }


def _action(name: str, **params) -> dict:
    return {"WFWorkflowActionIdentifier": f"is.workflow.actions.{name}", "WFWorkflowActionParameters": params}


def build_shortcut(url: str) -> dict:
    """The shortcut as a plist dict. It takes an image, or a link to one that it downloads
    on the device (so the server still never fetches URLs), and posts the bytes to `url`."""
    urls_id, download_id, group_id, post_id, dict_id, value_id = (_uuid() for _ in range(6))
    shortcut_input = _attachment({"Type": "ExtensionInput"})

    actions = [
        _action("detect.link", UUID=urls_id, WFInput=shortcut_input),
        _action(
            "conditional",
            GroupingIdentifier=group_id,
            WFControlFlowMode=0,
            WFCondition=CONDITION_HAS_ANY_VALUE,
            WFInput={"Type": "Variable", "Variable": _attachment(_output(urls_id, "URLs"))},
        ),
        _action("downloadurl", UUID=download_id, WFHTTPMethod="GET", WFURL=_text_with(_output(urls_id, "URLs"))),
        _action("setvariable", WFVariableName="Image", WFInput=_attachment(_output(download_id, "Contents of URL"))),
        _action("conditional", GroupingIdentifier=group_id, WFControlFlowMode=1),
        _action("setvariable", WFVariableName="Image", WFInput=shortcut_input),
        _action("conditional", GroupingIdentifier=group_id, WFControlFlowMode=2, UUID=_uuid()),
    ]
    post_index = len(actions)
    actions += [
        _action(
            "downloadurl",
            UUID=post_id,
            WFURL=url,
            WFHTTPMethod="POST",
            WFHTTPBodyType="File",
            WFRequestVariable=_attachment({"Type": "Variable", "VariableName": "Image"}),
        ),
        _action("detect.dictionary", UUID=dict_id, WFInput=_attachment(_output(post_id, "Contents of URL"))),
        _action(
            "getvalueforkey",
            UUID=value_id,
            WFDictionaryKey="message",
            WFGetDictionaryValueType="Value",
            WFInput=_attachment(_output(dict_id, "Dictionary")),
        ),
        _action("notification", WFNotificationActionBody=_text_with(_output(value_id, "Dictionary Value"))),
    ]

    return {
        "WFWorkflowClientVersion": "2900",
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowMinimumClientVersionString": "900",
        "WFWorkflowIcon": {"WFWorkflowIconStartColor": 431817727, "WFWorkflowIconGlyphNumber": 59511},
        # A signed file can't be edited before import, so this is how a recipient sets their own address
        "WFWorkflowImportQuestions": [
            {
                "ActionIndex": post_index,
                "Category": "Parameter",
                "DefaultValue": url,
                "ParameterKey": "WFURL",
                "Text": "What is your ArtBuff send-image URL?",
            }
        ],
        "WFWorkflowInputContentItemClasses": ["WFImageContentItem", "WFURLContentItem", "WFSafariWebPageContentItem"],
        "WFWorkflowTypes": ["ActionExtension"],
        "WFWorkflowNoInputBehavior": {"Name": "WFWorkflowNoInputBehaviorShowError", "Parameters": {}},
        "WFWorkflowActions": actions,
    }


def _sign_command(unsigned: Path, output: Path) -> list[str]:
    return ["shortcuts", "sign", "-m", "anyone", "-i", str(unsigned), "-o", str(output)]


def sign(data: bytes, output: Path) -> None:
    """Sign an unsigned shortcut so anyone can import it, exiting if `shortcuts sign` fails."""
    with tempfile.TemporaryDirectory() as tmp:
        unsigned = Path(tmp) / "unsigned.shortcut"
        unsigned.write_bytes(data)
        result = subprocess.run(_sign_command(unsigned, output))
    if result.returncode:
        raise SystemExit(result.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=DEFAULT_URL, help="ArtBuff's send-image URL, offered as the default on import")
    parser.add_argument("--output", type=Path, default=Path("dist") / f"{NAME}.shortcut")
    parser.add_argument("--no-sign", action="store_true", help="write an unsigned copy beside --output and print the command to sign it")
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    data = plistlib.dumps(build_shortcut(args.url), fmt=plistlib.FMT_BINARY)
    if args.no_sign:
        unsigned = args.output.with_name(f"{args.output.stem} unsigned{args.output.suffix}")
        unsigned.write_bytes(data)
        print(
            "This shortcut is unsigned, so Shortcuts won't import it. To sign it, run this on a Mac\n"
            "signed in to iCloud:\n\n"
            f"  {shlex.join(_sign_command(unsigned, args.output))}\n",
            file=sys.stderr,
        )
        print(unsigned)
    else:
        sign(data, args.output)
        print(args.output)


if __name__ == "__main__":
    main()
