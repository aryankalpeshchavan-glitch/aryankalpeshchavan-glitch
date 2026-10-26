import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from scripts.postprocess_profile_3d import (
    LANGUAGE_COLORS,
    SVG,
    postprocess_svg,
)


class Profile3DPostprocessTests(unittest.TestCase):
    def test_applies_exact_daily_tooltips_and_recolors_language_chart(self):
        svg = """<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="850">
  <style>.fill-bg { fill: #0d1117; }</style>
  <rect class="fill-bg" width="1280" height="850"/>
  <g>
    <g><rect class="cont-top-0"/><rect class="cont-left-0"/><rect class="cont-right-0"/></g>
    <g><rect class="cont-top-4"/><rect class="cont-left-4"/><rect class="cont-right-4"/></g>
  </g>
  <g transform="translate(40, 580)">
    <g transform="translate(273, 0)">
      <rect class="stroke-bg" fill="#3572A5"/>
      <rect class="stroke-bg" fill="#f1e05a"/>
      <text class="fill-fg">Python</text>
      <text class="fill-fg">JavaScript</text>
    </g>
    <g transform="translate(130, 130)">
      <path d="M0,0A1,1 0 0,1 1,0Z" style="fill: #3572A5"><title>Python 8</title></path>
      <path d="M0,0A1,1 0 0,1 -1,0Z" style="fill: #f1e05a"><title>JavaScript 3</title></path>
    </g>
  </g>
</svg>"""
        calendar_days = [
            {"date": "2026-10-25T00:00:00.000Z", "contributionCount": 0},
            {"date": "2026-10-26T00:00:00.000Z", "contributionCount": 1},
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "calendar.svg"
            output.write_text(svg, encoding="utf-8")

            postprocess_svg(output, calendar_days)

            root = ET.parse(output).getroot()
            calendar_group = root.find(f"{SVG}g")
            bars = [
                group
                for group in calendar_group
                if group.tag == f"{SVG}g"
            ]
            expected_titles = [
                "October 25, 2026\n0 contributions",
                "October 26, 2026\n1 contribution",
            ]
            self.assertEqual(
                [bar.findtext(f"{SVG}title") for bar in bars],
                expected_titles,
            )
            for bar, expected in zip(bars, expected_titles, strict=True):
                self.assertEqual(
                    [
                        rect.findtext(f"{SVG}title")
                        for rect in bar.findall(f"{SVG}rect")
                    ],
                    [expected, expected, expected],
                )

            labels = [element.text for element in root.iter(f"{SVG}text")]
            self.assertEqual(labels, ["Python", "JavaScript"])
            paths = list(root.iter(f"{SVG}path"))
            self.assertEqual(
                [path.get("d") for path in paths],
                ["M0,0A1,1 0 0,1 1,0Z", "M0,0A1,1 0 0,1 -1,0Z"],
            )
            self.assertEqual(
                [path.findtext(f"{SVG}title") for path in paths],
                ["Python 8", "JavaScript 3"],
            )
            self.assertEqual(
                [path.get("style") for path in paths],
                [f"fill: {LANGUAGE_COLORS[0]}", f"fill: {LANGUAGE_COLORS[1]}"],
            )
            markers = [
                marker
                for marker in root.iter(f"{SVG}rect")
                if marker.get("class") == "stroke-bg"
            ]
            self.assertEqual(
                [marker.get("fill") for marker in markers],
                [LANGUAGE_COLORS[0], LANGUAGE_COLORS[1]],
            )
            self.assertIn("#0d1117", root.findtext(f"{SVG}style"))

    def test_refuses_calendar_data_that_does_not_match_generated_days(self):
        svg = """<svg xmlns="http://www.w3.org/2000/svg">
  <g><g><rect class="cont-top-0"/><rect class="cont-left-0"/><rect class="cont-right-0"/></g></g>
</svg>"""
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "calendar.svg"
            output.write_text(svg, encoding="utf-8")
            original = output.read_bytes()

            with self.assertRaisesRegex(
                RuntimeError, "refusing to attach mismatched tooltips"
            ):
                postprocess_svg(output, [])

            self.assertEqual(output.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
