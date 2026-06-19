import argparse
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import cv2


BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


def run_command(cmd, *, stdout=None, text=True):
    """
    Run a command and raise a useful error if it fails.
    """
    try:
        if stdout is not None:
            return subprocess.run(
                cmd,
                check=True,
                stdout=stdout,
                stderr=subprocess.PIPE,
                text=False,
            )

        return subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=text,
        )

    except FileNotFoundError:
        raise RuntimeError(
            "Command not found. Make sure adb is installed and available in PATH."
        )

    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")

        raise RuntimeError(
            f"Command failed:\n{' '.join(cmd)}\n\nError:\n{stderr or exc}"
        )


def get_online_devices():
    result = run_command(["adb", "devices"])
    devices = []

    for line in result.stdout.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue

        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])

    return devices


def split_package_activity(raw_app):
    """
    Split package/activity and expand shorthand activity names.

    Example:
    com.example.app/.MainActivity

    Becomes:
    package = com.example.app
    activity = com.example.app.MainActivity
    """
    if "/" not in raw_app:
        return raw_app, "Unknown"

    package, activity = raw_app.split("/", 1)

    if activity.startswith("."):
        activity = package + activity

    return package, activity


def get_current_active_app(device_id):
    """
    Try to get the currently focused Android app/activity.
    """
    window_patterns = [
        re.compile(r"mCurrentFocus=.*?\s([a-zA-Z0-9_.]+/[a-zA-Z0-9_.$]+)"),
        re.compile(r"mFocusedApp=.*?\s([a-zA-Z0-9_.]+/[a-zA-Z0-9_.$]+)"),
    ]

    try:
        window_result = run_command([
            "adb",
            "-s",
            device_id,
            "shell",
            "dumpsys",
            "window",
        ])

        for pattern in window_patterns:
            match = pattern.search(window_result.stdout)
            if match:
                raw_app = match.group(1)
                package, activity = split_package_activity(raw_app)
                return {
                    "package": package,
                    "activity": activity,
                    "raw": raw_app,
                }

    except RuntimeError:
        pass

    activity_patterns = [
        re.compile(r"topResumedActivity=.*?\s([a-zA-Z0-9_.]+/[a-zA-Z0-9_.$]+)"),
        re.compile(r"mResumedActivity=.*?\s([a-zA-Z0-9_.]+/[a-zA-Z0-9_.$]+)"),
    ]

    try:
        activity_result = run_command([
            "adb",
            "-s",
            device_id,
            "shell",
            "dumpsys",
            "activity",
            "activities",
        ])

        for pattern in activity_patterns:
            match = pattern.search(activity_result.stdout)
            if match:
                raw_app = match.group(1)
                package, activity = split_package_activity(raw_app)
                return {
                    "package": package,
                    "activity": activity,
                    "raw": raw_app,
                }

    except RuntimeError:
        pass

    return {
        "package": "Unknown",
        "activity": "Unknown",
        "raw": "Unknown",
    }


def extract_bounds(node):
    bounds_str = node.get("bounds")
    if not bounds_str:
        return None

    match = BOUNDS_RE.fullmatch(bounds_str)
    if not match:
        return None

    left, top, right, bottom = map(int, match.groups())

    if right <= left or bottom <= top:
        return None

    return left, top, right, bottom


def capture_ui_xml(device_id, local_xml_path):
    remote_xml_path = "/sdcard/current_ui.xml"

    run_command([
        "adb",
        "-s",
        device_id,
        "shell",
        "uiautomator",
        "dump",
        remote_xml_path,
    ])

    run_command([
        "adb",
        "-s",
        device_id,
        "pull",
        remote_xml_path,
        str(local_xml_path),
    ])

    try:
        run_command([
            "adb",
            "-s",
            device_id,
            "shell",
            "rm",
            "-f",
            remote_xml_path,
        ])
    except RuntimeError:
        pass


def capture_screenshot(device_id, local_screenshot_path):
    with local_screenshot_path.open("wb") as screenshot_file:
        run_command(
            ["adb", "-s", device_id, "exec-out", "screencap", "-p"],
            stdout=screenshot_file,
        )


def get_unique_nodes_with_bounds(root):
    seen_bounds = set()
    nodes = []

    for node in root.iter():
        bounds = extract_bounds(node)
        if bounds is None:
            continue

        if bounds in seen_bounds:
            continue

        seen_bounds.add(bounds)

        nodes.append({
            "number": len(nodes) + 1,
            "bounds": bounds,
            "class": node.get("class", ""),
            "text": node.get("text", ""),
            "resource_id": node.get("resource-id", ""),
            "content_desc": node.get("content-desc", ""),
        })

    return nodes


def draw_label(image, label, x, y):
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.8
    outline_thickness = 4
    text_thickness = 2

    cv2.putText(
        image,
        label,
        (x, y),
        font,
        font_scale,
        (255, 255, 255),
        outline_thickness,
        cv2.LINE_AA,
    )

    cv2.putText(
        image,
        label,
        (x, y),
        font,
        font_scale,
        (0, 0, 0),
        text_thickness,
        cv2.LINE_AA,
    )


def annotate_screenshot(screenshot_path, annotated_path, nodes, draw_boxes=False):
    image = cv2.imread(str(screenshot_path))

    if image is None:
        raise RuntimeError(f"Could not read screenshot: {screenshot_path}")

    height, width = image.shape[:2]

    for item in nodes:
        number = item["number"]
        left, top, right, bottom = item["bounds"]

        label_x = min(max(left + 8, 0), width - 1)
        label_y = min(max(top + 28, 25), height - 5)

        if draw_boxes:
            cv2.rectangle(
                image,
                (left, top),
                (right, bottom),
                (255, 255, 255),
                2,
            )
            cv2.rectangle(
                image,
                (left, top),
                (right, bottom),
                (0, 0, 0),
                1,
            )

        draw_label(image, str(number), label_x, label_y)

    cv2.imwrite(str(annotated_path), image)


def print_nodes(nodes):
    print("\nNodes with unique bounds:\n")

    for item in nodes:
        number = item["number"]
        bounds = item["bounds"]
        class_name = item["class"]
        text = item["text"]
        resource_id = item["resource_id"]
        content_desc = item["content_desc"]

        extra_parts = []

        if class_name:
            extra_parts.append(f"class={class_name}")

        if resource_id:
            extra_parts.append(f"id={resource_id}")

        if text:
            extra_parts.append(f'text="{text}"')

        if content_desc:
            extra_parts.append(f'content-desc="{content_desc}"')

        extra = " | ".join(extra_parts)

        if extra:
            print(f"{number}. Bounds: {bounds} | {extra}")
        else:
            print(f"{number}. Bounds: {bounds}")


def main():
    parser = argparse.ArgumentParser(
        description="Capture Android UI hierarchy and annotate a screenshot with node numbers."
    )

    parser.add_argument(
        "--device",
        help="Specific adb device ID. If omitted, the first online device is used.",
    )

    parser.add_argument(
        "--xml",
        default="current_ui.xml",
        help="Output path for the pulled UI XML.",
    )

    parser.add_argument(
        "--screenshot",
        default="current_screenshot.png",
        help="Output path for the raw screenshot.",
    )

    parser.add_argument(
        "--annotated",
        default="annotated_screenshot.png",
        help="Output path for the annotated screenshot.",
    )

    parser.add_argument(
        "--draw-boxes",
        action="store_true",
        help="Draw rectangles around each unique node bounds.",
    )

    args = parser.parse_args()

    xml_path = Path(args.xml)
    screenshot_path = Path(args.screenshot)
    annotated_path = Path(args.annotated)

    devices = get_online_devices()

    if not devices:
        raise RuntimeError(
            "No online adb devices found. Check that USB debugging is enabled and the device is authorized."
        )

    device_id = args.device or devices[0]

    if device_id not in devices:
        raise RuntimeError(
            f"Device '{device_id}' is not online. Online devices: {', '.join(devices)}"
        )

    print(f"Using device: {device_id}")

    active_app = get_current_active_app(device_id)

    print("\nCurrent active app:")
    print(f"Package:  {active_app['package']}")
    print(f"Activity: {active_app['activity']}")
    print(f"Raw:      {active_app['raw']}")

    capture_ui_xml(device_id, xml_path)
    capture_screenshot(device_id, screenshot_path)

    tree = ET.parse(xml_path)
    root = tree.getroot()

    nodes = get_unique_nodes_with_bounds(root)

    print_nodes(nodes)

    annotate_screenshot(
        screenshot_path=screenshot_path,
        annotated_path=annotated_path,
        nodes=nodes,
        draw_boxes=args.draw_boxes,
    )

    print(f"\nSaved raw screenshot: {screenshot_path}")
    print(f"Saved annotated screenshot: {annotated_path}")
    print(f"Saved UI XML: {xml_path}")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        print(f"\nError: {error}", file=sys.stderr)
        sys.exit(1)
