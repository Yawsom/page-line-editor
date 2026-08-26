import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import align_report as alignment

PAGE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<PcGts xmlns="http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15">
  <Metadata><LastChange>old</LastChange></Metadata>
  <Page imageFilename="1r.jpg">
    <TextRegion id="r1" custom="readingOrder {{index:4;}}">
      <Coords points="0,0 100,0 100,100 0,100"/>
      <TextLine id="l1" custom="readingOrder {{index:8;}}">
        <Coords points="0,0 100,0 100,20 0,20"/>
        <Baseline points="0,15 100,15"/>
        <TextEquiv><Unicode>{first_text}</Unicode></TextEquiv>
      </TextLine>
      <TextEquiv><Unicode>STALE REGION ONE</Unicode></TextEquiv>
    </TextRegion>
    <TextRegion id="r2" custom="readingOrder {{index:5;}}">
      <Coords points="0,200 100,200 100,300 0,300"/>
      <TextLine id="l2" custom="readingOrder {{index:9;}}">
        <Coords points="0,200 100,200 100,220 0,220"/>
        <Baseline points="0,215 100,215"/>
        <TextEquiv><Unicode>old two</Unicode></TextEquiv>
      </TextLine>
      <TextEquiv><Unicode>STALE REGION TWO</Unicode></TextEquiv>
    </TextRegion>
  </Page>
</PcGts>
"""


def xml_line(line_id: str, text: str, y: float = 10) -> alignment.XmlLine:
    return alignment.XmlLine(
        ids=[line_id],
        text=text,
        baseline_y=y,
        bbox=alignment.BBox(0, int(y), 500, int(y) + 20),
        source_index=0,
    )


class AlignmentRegressionTests(unittest.TestCase):
    def rewrite(self, source: str, alignments, **kwargs):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        src = Path(temp_dir.name) / "source.xml"
        dest = Path(temp_dir.name) / "corrected.xml"
        src.write_text(source, encoding="utf-8")
        stats = alignment.rewrite_page_xml(src, alignments, dest, **kwargs)
        return ET.parse(dest), stats

    def test_meaningful_marks_are_not_normalized_away(self):
        self.assertEqual(alignment.normalize_for_match("⦿"), "⦿")
        self.assertEqual(alignment.normalize_for_match("✢"), "✢")
        self.assertEqual(alignment.normalize_for_match("✣"), "✣")
        self.assertEqual(alignment.normalize_for_match(":"), ":")
        self.assertLess(alignment.similarity("⦿", "✢"), 1.0)
        self.assertEqual(alignment.similarity("سلام؟", "سلام"), 1.0)

    def test_uncertain_extra_is_preserved_by_default(self):
        source = PAGE_XML.format(first_text="xxxx")
        results = alignment.dp_align(
            [xml_line("l1", "xxxx")], [alignment.GtLine(0, "سلام")]
        )
        tree, stats = self.rewrite(source, results)
        ids = {
            line.get("id")
            for line in tree.findall(".//p:TextLine", alignment.PAGE_NS)
        }
        self.assertIn("l1", ids)
        self.assertEqual(stats["preserved_extras"], 1)
        self.assertEqual(stats["deleted"], 0)

    def test_delete_all_extras_is_explicit_opt_in(self):
        source = PAGE_XML.format(first_text="xxxx")
        results = alignment.dp_align(
            [xml_line("l1", "xxxx")], [alignment.GtLine(0, "سلام")]
        )
        tree, stats = self.rewrite(source, results, delete_all_extras=True)
        ids = {
            line.get("id")
            for line in tree.findall(".//p:TextLine", alignment.PAGE_NS)
        }
        self.assertNotIn("l1", ids)
        self.assertEqual(stats["deleted"], 1)

    def test_confirmed_noise_extra_is_deleted_by_default(self):
        source = PAGE_XML.format(first_text="1")
        noise_line = xml_line("l1", "1")
        noise_line.noise = True
        results = alignment.dp_align([noise_line], [])
        tree, stats = self.rewrite(source, results)
        ids = {
            line.get("id")
            for line in tree.findall(".//p:TextLine", alignment.PAGE_NS)
        }
        self.assertNotIn("l1", ids)
        self.assertEqual(stats["deleted"], 1)
        self.assertEqual(stats["preserved_extras"], 0)

    def test_region_order_is_unique_and_region_text_is_cleared(self):
        source = PAGE_XML.format(first_text="old one")
        results = [
            alignment.make_alignment(
                [xml_line("l1", "old one")], [alignment.GtLine(0, "new one")]
            ),
            alignment.make_alignment(
                [xml_line("l2", "old two", 215)],
                [alignment.GtLine(1, "new two")],
            ),
        ]
        tree, _ = self.rewrite(source, results)
        regions = tree.findall(".//p:TextRegion", alignment.PAGE_NS)
        self.assertIn("readingOrder {index:0;}", regions[0].get("custom", ""))
        self.assertIn("readingOrder {index:1;}", regions[1].get("custom", ""))
        for region in regions:
            unicode_el = region.find("p:TextEquiv/p:Unicode", alignment.PAGE_NS)
            self.assertIsNotNone(unicode_el)
            self.assertIsNone(unicode_el.text)


if __name__ == "__main__":
    unittest.main()
