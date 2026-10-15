"""Security and useful-content checks for inert slide/PDF extraction."""

from __future__ import annotations

import io
from pathlib import Path
import subprocess
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from magi import attachments


def slide_xml(text: str) -> str:
    return (
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        f'<p:cSld><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:cSld></p:sld>'
    )


class AttachmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def pptx(self, parts: dict[str, str | bytes], name: str = "slides.pptx") -> Path:
        target = self.base / name
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for part, content in parts.items():
                archive.writestr(part, content)
        return target

    def test_slide_text_is_in_numeric_order_and_media_notes_are_ignored(self):
        target = self.pptx({
            "ppt/slides/slide10.xml": slide_xml("TENTH"),
            "ppt/slides/slide2.xml": slide_xml("SECOND"),
            "ppt/slides/slide1.xml": slide_xml("FIRST 日本語"),
            "ppt/notesSlides/notesSlide1.xml": slide_xml("PRIVATE NOTE"),
            "ppt/media/image1.png": b"UNPARSED IMAGE",
        })
        with patch.object(zipfile.ZipFile, "extract", side_effect=AssertionError("no extraction")), \
             patch.object(zipfile.ZipFile, "extractall", side_effect=AssertionError("no extraction")):
            result = attachments.extract_attachment(target)
        self.assertLess(result["text"].index("FIRST"), result["text"].index("SECOND"))
        self.assertLess(result["text"].index("SECOND"), result["text"].index("TENTH"))
        self.assertNotIn("PRIVATE NOTE", result["text"])
        self.assertNotIn("UNPARSED IMAGE", result["text"])
        self.assertIn("speaker notes", " ".join(result["limitations"]))

    def test_presentation_order_is_used_when_complete(self):
        target = self.pptx({
            "ppt/slides/slide1.xml": slide_xml("ONE"),
            "ppt/slides/slide2.xml": slide_xml("TWO"),
            "ppt/presentation.xml": (
                '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<p:sldIdLst><p:sldId id="2" r:id="r2"/><p:sldId id="1" r:id="r1"/>'
                '</p:sldIdLst></p:presentation>'
            ),
            "ppt/_rels/presentation.xml.rels": (
                '<Relationships><Relationship Id="r1" Target="slides/slide1.xml"/>'
                '<Relationship Id="r2" Target="slides/slide2.xml"/></Relationships>'
            ),
        })
        result = attachments.extract_attachment(target)
        self.assertLess(result["text"].index("TWO"), result["text"].index("ONE"))

    def test_slide_count_and_character_limits_are_explicit(self):
        target = self.pptx({f"ppt/slides/slide{i}.xml": slide_xml(f"Claim {i}") for i in range(1, 102)})
        result = attachments.extract_attachment(target)
        self.assertTrue(result["truncated"])
        self.assertIn("Claim 100", result["text"])
        self.assertNotIn("Claim 101", result["text"])
        bounded = attachments.extract_attachment(target, max_chars=17)
        self.assertEqual(len(bounded["text"]), 17)
        self.assertTrue(bounded["truncated"])

    def test_dtd_entities_and_unsafe_zip_names_are_rejected(self):
        xml = '<!DOCTYPE sld [<!ENTITY secret SYSTEM "file:///private">]>' + slide_xml("&secret;")
        target = self.pptx({"ppt/slides/slide1.xml": xml})
        result = attachments.extract_attachment(target)
        self.assertIsNone(result["text"])
        self.assertIn("DTD", " ".join(result["limitations"]))
        target = self.pptx({"ppt/slides/slide1.xml": slide_xml("fine"), "../outside": "no"})
        result = attachments.extract_attachment(target)
        self.assertIsNone(result["text"])
        self.assertIn("unsafe", " ".join(result["limitations"]))

    def test_zip_expansion_and_compression_bounds_are_checked_before_xml_read(self):
        target = self.pptx({"ppt/slides/slide1.xml": slide_xml("normal")})
        with patch.object(attachments, "MAX_ZIP_EXPANDED_BYTES", 3), \
             patch.object(zipfile.ZipFile, "open", side_effect=AssertionError("must not decompress")):
            result = attachments.extract_attachment(target)
        self.assertIsNone(result["text"])
        target = self.pptx({"ppt/slides/slide1.xml": slide_xml("a" * 100_000)})
        with patch.object(zipfile.ZipFile, "open", side_effect=AssertionError("must not decompress")):
            result = attachments.extract_attachment(target)
        self.assertIsNone(result["text"])
        self.assertIn("compression ratio", " ".join(result["limitations"]))

    def test_corrupt_deflate_data_is_reported_as_unanalysed(self):
        target = self.pptx({"ppt/slides/slide1.xml": slide_xml("normal")})
        with zipfile.ZipFile(target) as archive:
            offset = archive.infolist()[0].header_offset
        raw = bytearray(target.read_bytes())
        name_size, extra_size = struct.unpack_from("<HH", raw, offset + 26)
        data_offset = offset + 30 + name_size + extra_size
        raw[data_offset] = 0x07  # An invalid raw-DEFLATE block type.
        target.write_bytes(raw)
        self.assertIsNone(attachments.extract_attachment(target)["text"])

    def test_oversized_input_and_changed_identity_are_rejected_before_reading(self):
        target = self.pptx({"ppt/slides/slide1.xml": slide_xml("safe")})
        with patch.object(attachments, "MAX_INPUT_BYTES", 1), \
             patch.object(attachments.os, "open", side_effect=AssertionError("must not open")):
            result = attachments.extract_attachment(target)
        self.assertIsNone(result["text"])
        other = self.base / "other.pptx"
        other.write_bytes(b"PRIVATE")
        with patch.object(attachments.os, "open", side_effect=AssertionError("must not open")):
            result = attachments.extract_attachment(target, expected_stat=other.stat())
        self.assertIsNone(result["text"])
        self.assertIn("safety check", " ".join(result["limitations"]))

    def test_opened_file_identity_is_checked_before_read(self):
        target = self.pptx({"ppt/slides/slide1.xml": slide_xml("safe")})
        other = self.base / "other.pptx"
        other.write_bytes(b"PRIVATE")
        real_open = attachments.os.open
        with patch.object(attachments.os, "open", side_effect=lambda _path, flags: real_open(other, flags)):
            result = attachments.extract_attachment(target)
        self.assertIsNone(result["text"])
        self.assertIn("before reading", " ".join(result["limitations"]))

    def test_pdf_missing_optional_dependency_is_actionable(self):
        target = self.base / "slides.pdf"
        target.write_bytes(b"%PDF-1.7\n")
        with patch.object(attachments, "find_spec", return_value=None):
            result = attachments.extract_attachment(target)
        self.assertIsNone(result["text"])
        self.assertIn("python -m pip install pypdf", " ".join(result["limitations"]))

    def test_pdf_timeout_is_unanalysed_not_silent_success(self):
        target = self.base / "slides.pdf"
        target.write_bytes(b"%PDF-1.7\n")
        with patch.object(attachments, "find_spec", return_value=object()), \
             patch.object(attachments.subprocess, "run", side_effect=subprocess.TimeoutExpired("pdf", 15)):
            result = attachments.extract_attachment(target)
        self.assertIsNone(result["text"])
        self.assertIn("time limit", " ".join(result["limitations"]))

    @unittest.skipUnless(attachments.find_spec("pypdf"), "Optional pypdf is unavailable")
    def test_real_pdf_worker_extracts_text_in_a_bounded_process(self):
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

        writer = PdfWriter()
        page = writer.add_blank_page(width=300, height=200)
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        })
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 20 100 Td (Readable slide claim) Tj ET")
        page[NameObject("/Contents")] = stream
        encoded = io.BytesIO()
        writer.write(encoded)
        target = self.base / "slides.pdf"
        target.write_bytes(encoded.getvalue())
        result = attachments.extract_attachment(target)
        self.assertIn("Readable slide claim", result["text"])
        self.assertFalse(result["truncated"])
        bounded = attachments.extract_attachment(target, max_chars=12)
        self.assertEqual(len(bounded["text"]), 12)
        self.assertTrue(bounded["truncated"])

    @unittest.skipUnless(attachments.find_spec("pypdf"), "Optional pypdf is unavailable")
    def test_pdf_page_limit_and_encryption_are_explicit(self):
        from pypdf import PdfWriter

        writer = PdfWriter()
        for _ in range(101):
            writer.add_blank_page(width=100, height=100)
        encoded = io.BytesIO()
        writer.write(encoded)
        target = self.base / "pages.pdf"
        target.write_bytes(encoded.getvalue())
        result = attachments.extract_attachment(target)
        self.assertTrue(result["truncated"])
        self.assertIn("[Page 100]", result["text"])
        self.assertNotIn("[Page 101]", result["text"])
        writer.encrypt("test-only-password")
        encoded = io.BytesIO()
        writer.write(encoded)
        target.write_bytes(encoded.getvalue())
        result = attachments.extract_attachment(target)
        self.assertIsNone(result["text"])
        self.assertIn("Encrypted", " ".join(result["limitations"]))

    def test_malformed_files_and_empty_budget_do_not_crash_or_claim_analysis(self):
        target = self.base / "slides.pptx"
        target.write_bytes(b"not a zip")
        result = attachments.extract_attachment(target)
        self.assertIsNone(result["text"])
        with patch.object(attachments.os, "open", side_effect=AssertionError("no budget")):
            result = attachments.extract_attachment(target, max_chars=0)
        self.assertIsNone(result["text"])
        self.assertTrue(result["truncated"])


if __name__ == "__main__":
    unittest.main()
