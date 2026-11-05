"""題目內容中的圖片：資料驗證、拆解與考生展示資料。"""
import json
import unittest

from oes.core import exam as E
from oes.core import question_types as C
from oes.core import session as S
from tests.helpers import CORRECT_Y, fx

PNG_1PX = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


def with_image():
    q = fx("demoYesNo")
    q["prompt"] = "請看下圖：\n{{image:img1}}\n再回答問題。"
    q["images"] = [{"id": "img1", "mime": "image/png", "data": PNG_1PX}]
    return q


class ImageTests(unittest.TestCase):
    def test_valid_and_split(self):
        q = with_image()
        self.assertEqual(C.validate(q), [])
        self.assertEqual(C.split_prompt(q["prompt"]),
                         [("text", "請看下圖：\n"), ("image", "img1"), ("text", "\n再回答問題。")])
        self.assertEqual(C.image_bytes(q["images"][0])[:4], b"\x89PNG")

    def test_missing_image_reference(self):
        q = with_image(); del q["images"]
        self.assertTrue(any("img1" in e["message"] for e in C.validate(q)))

    def test_image_width(self):
        q = with_image(); q["images"][0]["width"] = 400
        self.assertEqual(C.validate(q), [])
        self.assertEqual(C.image_width(q["images"][0]), 400)
        self.assertIsNone(C.image_width({"id": "x"}))
        for bad in (0, 15, 1601, 12.5, "400", True, None):
            q["images"][0]["width"] = bad
            with self.subTest(width=bad):
                self.assertTrue(any(e["path"] == "images[0].width" for e in C.validate(q)))
                self.assertIsNone(C.image_width(q["images"][0]))

    def test_image_width_kept_for_candidate(self):
        q = with_image(); q["images"][0]["width"] = 300
        q["status"] = "ready"
        exam = E.new_exam("t")
        exam["questions"].append({"sectionId": None, "question": q})
        self.assertIn('"width": 300', json.dumps(S.build_session(exam), ensure_ascii=False))

    def test_bad_image_entries(self):
        for mutate in (lambda q: q["images"][0].update(mime="image/svg+xml"),
                       lambda q: q["images"][0].update(data="not base64!!"),
                       lambda q: q["images"][0].update(extra=1),
                       lambda q: q["images"].append(dict(q["images"][0]))):
            q = with_image(); mutate(q)
            with self.subTest():
                self.assertTrue(C.validate(q))

    def test_candidate_gets_referenced_images_only(self):
        q = with_image()
        q["images"].append({"id": "unused", "mime": "image/png", "data": PNG_1PX})
        dto = C.for_candidate(q)
        self.assertEqual([i["id"] for i in dto["images"]], ["img1"])
        self.assertNotIn("correctAnswer", json.dumps(dto))

    def test_no_images_field_when_text_only(self):
        self.assertNotIn("images", C.for_candidate(fx("demoYesNo")))

    def test_images_survive_json_session_and_grading(self):
        ex = E.new_exam(); ex["questions"].append({"sectionId": None, "question": with_image()})
        kind, data = E.parse_import(E.export_exam_json(ex))
        self.assertEqual(data["questions"][0]["question"]["images"][0]["data"], PNG_1PX)
        s = S.build_session(data)
        self.assertEqual(s["questions"][0]["presented"]["images"][0]["id"], "img1")
        S.set_answer(s, "demo-yes-no", CORRECT_Y)
        self.assertEqual(S.finish(s)["score"], 1)


class OptionImageCoreTests(unittest.TestCase):
    def _mc(self):
        q = C.new_question("multiple_choice", "mc")
        q.update(status="ready", prompt="選出圖片", correctAnswer=["o1"])
        q["options"][0]["text"] = "{{image:img1}}"
        q["images"] = [{"id": "img1", "mime": "image/png", "data": PNG_1PX}]
        return q

    def test_option_only_image_is_valid(self):
        self.assertEqual(C.validate(self._mc()), [])
        self.assertEqual(C.question_image_refs(self._mc()), ["img1"])

    def test_option_missing_image_reported_on_option(self):
        q = self._mc(); del q["images"]
        self.assertTrue(any(e["path"] == "options[0].text" for e in C.validate(q)))

    def test_candidate_includes_option_images(self):
        dto = C.for_candidate(self._mc())
        self.assertEqual([i["id"] for i in dto["images"]], ["img1"])


if __name__ == "__main__":
    unittest.main()
