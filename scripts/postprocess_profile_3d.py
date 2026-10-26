#!/usr/bin/env python3
"""Apply the profile SVG theme and exact daily contribution tooltips."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path
from typing import Any


SVG_NS = "http://www.w3.org/2000/svg"
SVG = f"{{{SVG_NS}}}"
GRAPHQL_URL = "https://api.github.com/graphql"
LANGUAGE_COLORS = (
    "#0e4429",
    "#006d32",
    "#008f3a",
    "#26a641",
    "#39d353",
    "#56e875",
)
CALENDAR_FACE_CLASSES = ("cont-top-", "cont-left-", "cont-right-")
CALENDAR_PATHS = (
    Path("profile-3d-contrib/profile-green-animate.svg"),
    Path("profile-3d-contrib/profile-green.svg"),
)
CALENDAR_QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        weeks {
          contributionDays {
            date
            contributionCount
          }
        }
      }
    }
  }
}
"""


def fetch_contribution_days(username: str, token: str) -> list[dict[str, Any]]:
    request = urllib.request.Request(
        GRAPHQL_URL,
        data=json.dumps(
            {"query": CALENDAR_QUERY, "variables": {"login": username}}
        ).encode("utf-8"),
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "github-profile-3d-contrib-postprocessor",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(
            f"GitHub GraphQL request failed with HTTP {error.code}"
        ) from error
    except urllib.error.URLError as error:
        raise RuntimeError(
            f"GitHub GraphQL request failed: {error.reason}"
        ) from error

    if payload.get("errors"):
        messages = "; ".join(
            item.get("message", "Unknown GraphQL error")
            for item in payload["errors"]
        )
        raise RuntimeError(f"GitHub GraphQL returned errors: {messages}")
    try:
        weeks = payload["data"]["user"]["contributionsCollection"][
            "contributionCalendar"
        ]["weeks"]
    except (KeyError, TypeError) as error:
        raise RuntimeError(
            "GitHub GraphQL response did not contain a contribution calendar"
        ) from error

    calendar_days = [
        day for week in weeks for day in week["contributionDays"]
    ]
    if not calendar_days:
        raise RuntimeError("GitHub GraphQL returned an empty contribution calendar")
    return calendar_days


def _date_label(raw_date: str) -> str:
    parsed = date.fromisoformat(raw_date[:10])
    return f"{parsed.strftime('%B')} {parsed.day}, {parsed.year}"


def _calendar_bars(root: ET.Element) -> list[ET.Element]:
    candidates: list[list[ET.Element]] = []
    for group in root.iter(f"{SVG}g"):
        bars = []
        for child in list(group):
            if child.tag != f"{SVG}g":
                continue
            classes = [
                rect.get("class", "")
                for rect in child.findall(f"{SVG}rect")
            ]
            if all(
                any(class_name.startswith(prefix) for class_name in classes)
                for prefix in CALENDAR_FACE_CLASSES
            ):
                bars.append(child)
        if bars:
            candidates.append(bars)
    if len(candidates) != 1:
        raise RuntimeError(
            f"Expected one 3D calendar group, found {len(candidates)}"
        )
    return candidates[0]


def _language_chart(
    root: ET.Element,
) -> tuple[list[ET.Element], list[ET.Element], list[ET.Element]]:
    legends: list[tuple[list[ET.Element], list[ET.Element]]] = []
    for group in root.iter(f"{SVG}g"):
        labels = [
            child
            for child in list(group)
            if child.tag == f"{SVG}text"
            and child.get("class") == "fill-fg"
        ]
        markers = [
            child
            for child in list(group)
            if child.tag == f"{SVG}rect"
            and child.get("class") == "stroke-bg"
        ]
        if labels and len(labels) == len(markers):
            legends.append((labels, markers))

    if len(legends) != 1:
        raise RuntimeError(
            "Expected one language legend with matching markers, "
            f"found {len(legends)}"
        )
    labels, markers = legends[0]

    slices = [
        path
        for path in root.iter(f"{SVG}path")
        if path.get("d") is not None
        and path.find(f"{SVG}title") is not None
    ]
    if len(slices) != len(labels):
        raise RuntimeError(
            f"Language legend has {len(labels)} entries but chart has "
            f"{len(slices)} slices"
        )
    for label, path in zip(labels, slices, strict=True):
        title = path.findtext(f"{SVG}title") or ""
        if not title.startswith(f"{label.text or ''} "):
            raise RuntimeError("Language legend and donut slice order do not match")
    if len(labels) > len(LANGUAGE_COLORS):
        raise RuntimeError(
            "Language chart has more entries than the distinct green palette "
            "supports"
        )
    return labels, markers, slices


def _set_fill_style(element: ET.Element, color: str) -> None:
    declarations = [
        declaration.strip()
        for declaration in element.get("style", "").split(";")
        if declaration.strip()
        and declaration.split(":", 1)[0].strip().lower() != "fill"
    ]
    declarations.insert(0, f"fill: {color}")
    element.set("style", "; ".join(declarations))


def postprocess_svg(svg_path: Path, calendar_days: list[dict[str, Any]]) -> None:
    ET.register_namespace("", SVG_NS)
    try:
        root = ET.parse(svg_path).getroot()
    except (ET.ParseError, OSError) as error:
        raise RuntimeError(
            f"Could not parse generated SVG {svg_path}: {error}"
        ) from error
    if root.tag != f"{SVG}svg":
        raise RuntimeError(f"{svg_path} does not have an SVG root")

    bars = _calendar_bars(root)
    if len(bars) != len(calendar_days):
        raise RuntimeError(
            f"Generated calendar has {len(bars)} days but GitHub returned "
            f"{len(calendar_days)}; refusing to attach mismatched tooltips"
        )

    previous_day: date | None = None
    for bar, day_data in zip(bars, calendar_days, strict=True):
        raw_date = str(day_data.get("date", ""))
        try:
            day = date.fromisoformat(raw_date[:10])
            count = day_data["contributionCount"]
        except (TypeError, ValueError, KeyError) as error:
            raise RuntimeError(
                "GitHub returned invalid daily contribution data"
            ) from error
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise RuntimeError(
                f"GitHub returned an invalid contribution count for {raw_date}"
            )
        if previous_day is not None and day - previous_day != timedelta(days=1):
            raise RuntimeError(
                "GitHub contribution dates are not consecutive; refusing to "
                "attach mismatched tooltips"
            )
        previous_day = day

        count_label = "contribution" if count == 1 else "contributions"
        title_text = f"{_date_label(raw_date)}\n{count} {count_label}"
        for parent in (bar, *bar.findall(f"{SVG}rect")):
            for existing_title in parent.findall(f"{SVG}title"):
                parent.remove(existing_title)
            title = ET.Element(f"{SVG}title")
            title.text = title_text
            parent.insert(0, title)

    _, markers, slices = _language_chart(root)
    for index, (marker, chart_slice) in enumerate(
        zip(markers, slices, strict=True)
    ):
        color = LANGUAGE_COLORS[index]
        marker.set("fill", color)
        _set_fill_style(chart_slice, color)

    svg_path.write_bytes(
        ET.tostring(root, encoding="utf-8", xml_declaration=True)
    )


def main() -> None:
    username = os.environ.get("USERNAME", "").strip()
    token = os.environ.get("GITHUB_TOKEN", "")
    if not username:
        raise RuntimeError("USERNAME is required")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required")

    calendar_days = fetch_contribution_days(username, token)
    for svg_path in CALENDAR_PATHS:
        if not svg_path.is_file():
            raise RuntimeError(f"Expected generated SVG is missing: {svg_path}")
        postprocess_svg(svg_path, calendar_days)
        print(f"Post-processed {svg_path}")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        print(error, file=sys.stderr)
        raise SystemExit(1) from error
