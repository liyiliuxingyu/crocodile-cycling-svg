"""Sample this project's SVG animations into standalone, static video frames.

This deliberately implements only the linear SVG animation types used here.
It is not a general SMIL engine; unsupported animation features are rejected.
"""

from __future__ import annotations

import argparse
from bisect import bisect_right
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re

from lxml import etree, html


ROOT = Path(__file__).resolve().parents[1]
SVG_NS = "http://www.w3.org/2000/svg"
NUMBER = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
ANIMATION_TAGS = {"animate", "animateTransform", "animateMotion", "set"}
DEFAULT_FONT = "Noto Sans CJK SC, Source Han Sans SC, PingFang SC, Microsoft YaHei, sans-serif"


def local_name(node):
    return etree.QName(node).localname if isinstance(node.tag, str) else ""


def element(tag, **attrs):
    return etree.Element(f"{{{SVG_NS}}}{tag}", {key.replace("_", "-"): str(value)
                                               for key, value in attrs.items()})


def number(value):
    if abs(value) < 0.0000005:
        return "0"
    return f"{value:.6f}".rstrip("0").rstrip(".")


def seconds(raw):
    match = re.fullmatch(r"\s*(\d+(?:\.\d*)?|\.\d+)(ms|s)?\s*", raw)
    if not match:
        raise ValueError(f"Unsupported SVG clock value: {raw!r}")
    return float(match.group(1)) / (1000 if match.group(2) == "ms" else 1)


def root_path(value):
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def extract_scene(source):
    # Extract the original XML instead of parsing SVG as HTML, which would
    # lowercase case-sensitive names such as viewBox and animateTransform.
    match = re.search(r'<svg\b[^>]*\bid=["\']ride-scene["\'][\s\S]*?</svg>', source)
    if not match:
        raise ValueError('Could not find the SVG with id="ride-scene".')
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    return etree.fromstring(match.group(0).encode("utf-8"), parser)


def class_node(document, class_name):
    matches = document.xpath(
        '//*[contains(concat(" ", normalize-space(@class), " "), $name)]',
        name=f" {class_name} ",
    )
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one .{class_name} element.")
    return matches[0]


def text_content(node):
    return "".join(node.itertext()).strip()


@dataclass
class Animation:
    parent: etree._Element
    attribute: str
    transform_type: str | None
    duration: float
    times: list[float]
    chunks: list[str]
    values: list[list[float]]

    @classmethod
    def from_node(cls, node, cloud_period):
        tag = local_name(node)
        if tag not in {"animate", "animateTransform"}:
            raise ValueError(f"Unsupported animation element: {tag}")
        if node.get("calcMode", "linear") != "linear":
            raise ValueError("Only linear animation is supported.")
        if seconds(node.get("begin", "0s")) != 0:
            raise ValueError("Only animations beginning at 0s are supported.")
        if node.get("repeatCount") != "indefinite":
            raise ValueError("Only indefinite repeating animations are supported.")
        if node.get("additive", "replace") != "replace":
            raise ValueError("Additive animations are not supported.")
        if node.get("accumulate", "none") != "none":
            raise ValueError("Accumulating animations are not supported.")
        if any(key in node.attrib for key in ("end", "repeatDur", "by", "href")):
            raise ValueError("Unsupported timing or animation target feature.")
        attribute = node.get("attributeName")
        transform_type = node.get("type") if tag == "animateTransform" else None
        if tag == "animateTransform":
            if attribute != "transform" or transform_type not in {"translate", "rotate"}:
                raise ValueError("Only translate and rotate transforms are supported.")
        elif attribute not in {"d", "opacity"}:
            raise ValueError(f"Unsupported animated attribute: {attribute}")
        duration = seconds(node.get("dur", ""))
        if duration <= 0:
            raise ValueError("Animation durations must be positive.")
        # These are the two clouds in the supplied HTML. Change only the parsed
        # copy's timing; never write back to index.html or its generator.
        if transform_type == "translate" and duration in {18.0, 22.0}:
            duration = cloud_period
        if node.get("values") is not None:
            strings = [value.strip() for value in node.get("values").split(";")]
        elif node.get("from") is not None and node.get("to") is not None:
            strings = [node.get("from"), node.get("to")]
        else:
            raise ValueError("An animation must have values or both from and to.")
        if len(strings) < 2:
            raise ValueError("An animation needs at least two values.")
        chunks = NUMBER.split(strings[0])
        values = [[float(value) for value in NUMBER.findall(item)] for item in strings]
        if not values[0] or any(NUMBER.split(item) != chunks for item in strings):
            raise ValueError("Animated values must have matching numeric structure.")
        if any(not math.isfinite(value) for item in values for value in item):
            raise ValueError("Animation values must be finite.")
        if attribute == "d" and set(re.findall(r"[A-Za-z]", "".join(chunks))) - {"M", "L"}:
            raise ValueError("Only the matching M/L paths used by this scene are supported.")
        if transform_type == "translate" and len(values[0]) != 2:
            raise ValueError("This scene uses two-component translations.")
        if transform_type == "rotate" and len(values[0]) != 3:
            raise ValueError("This scene uses angle/cx/cy rotations.")
        if node.get("keyTimes"):
            times = [float(value) for value in node.get("keyTimes").split(";")]
        else:
            times = [index / (len(values) - 1) for index in range(len(values))]
        if (len(times) != len(values) or times[0] != 0 or times[-1] != 1
                or any(not math.isfinite(value) for value in times)
                or any(right <= left for left, right in zip(times, times[1:]))):
            raise ValueError("keyTimes must increase strictly from 0 to 1.")
        return cls(node.getparent(), attribute, transform_type, duration, times, chunks, values)

    def apply(self, time):
        cycles = time / self.duration
        phase = cycles - math.floor(cycles)
        if math.isclose(phase, 1, abs_tol=1e-10) or math.isclose(phase, 0, abs_tol=1e-10):
            phase = 0.0
        index = min(bisect_right(self.times, phase) - 1, len(self.times) - 2)
        fraction = (phase - self.times[index]) / (self.times[index + 1] - self.times[index])
        interpolated = [left + (right - left) * fraction
                        for left, right in zip(self.values[index], self.values[index + 1])]
        parts = [self.chunks[0]]
        for value, suffix in zip(interpolated, self.chunks[1:]):
            parts.extend([number(value), suffix])
        value = "".join(parts)
        if self.transform_type:
            value = f"{self.transform_type}({value})"
        # SMIL's default additive="replace" replaces the parent's base value.
        self.parent.set(self.attribute, value)


class Sampler:
    def __init__(self, source, width, height, cloud_period, font_family):
        self.scene = deepcopy(extract_scene(source))
        nodes = [node for node in self.scene.iter() if local_name(node) in ANIMATION_TAGS]
        self.animations = [Animation.from_node(node, cloud_period) for node in nodes]
        if not self.animations:
            raise ValueError("The source scene contains no supported animation.")
        for node in nodes:
            node.getparent().remove(node)
        document = html.fromstring(source)
        headings = document.xpath('//*[@id="page-title"]')
        if len(headings) != 1:
            raise ValueError('Expected one title with id="page-title".')
        heading = headings[0]
        span = heading.find("span")
        if span is None or not (heading.text or "").strip():
            raise ValueError("Expected the original two-line title structure.")
        first_line = heading.text.strip()
        second_line = text_content(span)
        self.title = first_line + second_line
        self.root = etree.Element(f"{{{SVG_NS}}}svg", nsmap={None: SVG_NS},
                                  width=str(width), height=str(height), viewBox="0 0 1920 1080")
        self.root.set("font-family", font_family)
        self.root.set("fill", "#294b39")
        title = element("title")
        title.text = "鳄鱼骑行日 · Croc & Cycle"
        self.root.append(title)
        self.root.append(element("rect", width=1920, height=1080, fill="#f4f2e9"))

        # A 16:9 export composition using the same artwork, title and captions.
        # The original scene keeps its 5:3 aspect ratio without cropping.
        logo = element("g", transform="translate(202 28) scale(1.05)")
        logo.set("color", "#294b39")
        header_svg = class_node(document, "wordmark").find("svg")
        if header_svg is not None:
            for child in header_svg:
                logo.append(deepcopy(child))
        self.root.append(logo)
        self.add_text(self.root, 257, 57, "CROC & CYCLE", 22, "#294b39", 800, letter_spacing=3)
        self.add_text(self.root, 1715, 56, text_content(class_node(document, "weather")),
                      16, "#7b8270", text_anchor="end", letter_spacing=1.2)
        self.scene.set("x", "200")
        self.scene.set("y", "96")
        self.scene.set("width", "1520")
        self.scene.set("height", "912")
        self.root.append(self.scene)
        self.root.append(element("rect", x=200, y=96, width=1520, height=912, rx=40,
                                 fill="none", stroke="#dedfd1", stroke_width=1.5))
        self.add_text(self.scene, 43, 48, text_content(class_node(document, "eyebrow")),
                      10, "#798368", 700, letter_spacing=2.2)
        self.add_text(self.scene, 43, 117, first_line, 62, "#294b39", 800, letter_spacing=-4)
        self.add_text(self.scene, 43, 193, second_line, 62, "#84945b", 800, letter_spacing=-4)
        self.add_text(self.scene, 43, 244, text_content(class_node(document, "intro-copy")),
                      12, "#8b8d78", letter_spacing=1.44)
        self.scene.append(element("path", d="M28 578H52", stroke="#a9b295", stroke_width=1))
        self.add_text(self.scene, 61, 582, text_content(class_node(document, "panel-caption")),
                      11, "#7b846b", letter_spacing=0.99)
        self.add_text(self.scene, 974, 582, text_content(class_node(document, "edition")),
                      10, "#879079", text_anchor="end", letter_spacing=1.6)
        footer = class_node(document, "footer-copy")
        strong = footer.find("strong")
        footer_break = footer.find("br")
        if strong is not None:
            self.add_text(self.root, 206, 1042, text_content(strong), 16, "#49613e", 600)
        if footer_break is not None and footer_break.tail:
            self.add_text(self.root, 206, 1066, footer_break.tail.strip(), 15, "#77836c")

    @staticmethod
    def add_text(parent, x, y, text, size, fill, weight=400, **attrs):
        node = element("text", x=x, y=y, font_size=size, fill=fill, font_weight=weight, **attrs)
        node.text = text
        parent.append(node)

    def frame(self, time):
        for animation in self.animations:
            animation.apply(time)
        return etree.tostring(self.root, encoding="utf-8", xml_declaration=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="index.html", help="Source HTML, relative to repository root")
    parser.add_argument("--output", default="build/frames", help="Static SVG frame directory")
    parser.add_argument("--duration", type=float, default=12.0, help="Seconds, default: 12")
    parser.add_argument("--fps", type=float, default=30.0, help="Frames per second, default: 30")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--cloud-period", type=float, default=12.0,
                        help="Period of both clouds in the sampled copy, default: 12")
    parser.add_argument("--font-family", default=DEFAULT_FONT, help="Installed SVG font fallback list")
    args = parser.parse_args()
    for key in ("duration", "fps", "cloud_period"):
        value = getattr(args, key)
        if not math.isfinite(value) or value <= 0:
            parser.error(f"--{key.replace('_', '-')} must be positive and finite")
    if args.width <= 0 or args.height <= 0 or args.width % 2 or args.height % 2:
        parser.error("Width and height must be positive even integers for yuv420p.")
    exact_count = args.duration * args.fps
    count = round(exact_count)
    if count < 1 or not math.isclose(exact_count, count, abs_tol=1e-8):
        parser.error("duration × fps must be a positive whole number of frames.")
    source_path = root_path(args.input)
    source_bytes = source_path.read_bytes()
    sampler = Sampler(source_bytes.decode("utf-8"), args.width, args.height,
                      args.cloud_period, args.font_family)
    output = root_path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    first = sampler.frame(0)
    end = sampler.frame(args.duration)
    for index in range(count):
        (output / f"frame-{index:06d}.svg").write_bytes(sampler.frame(index / args.fps))
    manifest = {
        "format_version": 1,
        "width": args.width,
        "height": args.height,
        "fps": args.fps,
        "duration_seconds": args.duration,
        "frame_count": count,
        "frame_pattern": "frame-%06d.svg",
        "animation_count": len(sampler.animations),
        "cloud_period_seconds": args.cloud_period,
        "loop_at_duration": first == end,
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "title": sampler.title,
        "font_family": args.font_family,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                           encoding="utf-8")
    if source_path.read_bytes() != source_bytes:
        raise RuntimeError("The source HTML changed while frames were being generated.")
    print(f"Sampled {count} SVG frames at {args.fps:g} fps: {output}")
    print(f"Animations: {len(sampler.animations)}; endpoint loop match: {first == end}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, etree.LxmlError) as error:
        raise SystemExit(f"Frame sampling failed: {error}") from error
