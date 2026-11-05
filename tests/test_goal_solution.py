"""解決方案評估題（Does this meet the goal?）：驗證、評分、考生資料、無法返回與系列題分組。"""
import random
import unittest

from oes.core import exam as E
from oes.core import question_types as C
from oes.core import session as S

PNG_1PX = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
SCENARIO = "網路中有一個 AD DS 網域 example.local。\n你需要找出擔任某個 FSMO 角色的伺服器。"


def goal(qid="g1", key=True, solution="在伺服器上執行某個命令。", no_return=True, prompt=SCENARIO):
    q = C.new_question("goal_solution", qid)
    q.update(status="ready", prompt=prompt, solution=solution, correctAnswer=key, noReturn=no_return)
    return q


def mc(qid):
    q = C.new_question("multiple_choice", qid)
    q.update(status="ready", prompt="題目", correctAnswer=["o1"])
    return q


class GoalSolutionTypeTests(unittest.TestCase):
    def test_template_is_valid_draft(self):
        q = C.new_question("goal_solution", "g1")
        self.assertEqual(C.validate(q), [])
        self.assertFalse(q["noReturn"])  # 預設可返回上一題
        self.assertTrue(C.validate(q, require_answer_key=True))

    def test_ready_requires_solution_and_key(self):
        self.assertEqual(C.validate(goal()), [])
        paths = {e["path"] for e in C.validate(goal(solution="  ", key=None))}
        self.assertEqual(paths, {"solution", "correctAnswer"})
        self.assertEqual(C.validate(goal(key=False)), [])

    def test_bad_fields(self):
        for field, value in (("solution", 3), ("noReturn", "yes"), ("correctAnswer", "yes")):
            q = goal()
            q[field] = value
            with self.subTest(field=field):
                self.assertTrue(any(e["path"] == field for e in C.validate(q)))
        q = goal()
        del q["correctAnswer"]
        self.assertTrue(any(e["path"] == "correctAnswer" for e in C.validate(q)))

    def test_grading(self):
        q = goal(key=False)
        self.assertEqual(C.grade(q, {"answer": False})["score"], 1)
        self.assertEqual(C.grade(q, {"answer": True})["score"], 0)
        self.assertEqual(C.grade(q, {})["status"], "incomplete")
        self.assertEqual(C.grade(q, {"answer": "No"})["status"], "invalid")
        self.assertEqual(C.grade(q, {"other": True})["status"], "invalid")

    def test_candidate_hides_key(self):
        dto = C.for_candidate(goal())
        self.assertNotIn("correctAnswer", dto)
        self.assertEqual((dto["solution"], dto["noReturn"]), ("在伺服器上執行某個命令。", True))

    def test_image_in_solution(self):
        q = goal(solution="如下圖：\n{{image:img1}}")
        self.assertTrue(any("img1" in e["message"] for e in C.validate(q)))
        q["images"] = [{"id": "img1", "mime": "image/png", "data": PNG_1PX}]
        self.assertEqual(C.validate(q), [])
        self.assertEqual(C.for_candidate(q)["images"][0]["id"], "img1")
        self.assertEqual(C.validate(goal(solution="{{image:img1}}") | {"images": q["images"]}), [])

    def test_summary(self):
        q = goal()
        row = C.grade(q, {"answer": True})["items"][0]
        self.assertEqual(C.summarize_selection(q, row, True), "Yes")
        self.assertEqual(C.summarize_selection(q, row, False), "No")


class NoReturnSessionTests(unittest.TestCase):
    def exam(self, *questions):
        exam = E.new_exam("t")
        for q in questions:
            exam["questions"].append({"sectionId": None, "question": q})
        return exam

    def test_lock_in_exam_mode(self):
        session = S.build_session(self.exam(goal("g1"), mc("m1"), goal("g2", no_return=False)))
        self.assertEqual(session["locked"], [])
        self.assertTrue(S.no_return(session, "g1"))
        self.assertFalse(S.no_return(session, "g2"))
        S.set_answer(session, "g1", {"answer": True})
        S.toggle_mark(session, "g1", True)
        S.lock_question(session, "g1")
        S.lock_question(session, "g1")
        S.lock_question(session, "m1")  # 一般題目不鎖定
        self.assertEqual(session["locked"], ["g1"])
        self.assertNotIn("g1", session["marked"])
        with self.assertRaises(ValueError):
            S.set_answer(session, "g1", {"answer": False})
        S.set_answer(session, "m1", {"selected": ["o1"]})
        S.set_answer(session, "g2", {"answer": True})
        report = S.finish(session)
        self.assertEqual(report["percent"], 100)

    def test_practice_mode_never_locks(self):
        session = S.build_session(self.exam(goal("g1")), mode="practice")
        self.assertFalse(S.no_return(session, "g1"))
        S.lock_question(session, "g1")
        self.assertEqual(session["locked"], [])

    def test_old_sessions_without_locked(self):
        session = S.build_session(self.exam(goal("g1")))
        del session["locked"]
        self.assertFalse(S.is_locked(session, "g1"))
        S.lock_question(session, "g1")
        self.assertTrue(S.is_locked(session, "g1"))

    def test_retake_clears_locks(self):
        session = S.build_session(self.exam(goal("g1")))
        S.lock_question(session, "g1")
        S.finish(session)
        fresh = S.retake(session, "all")
        self.assertEqual(fresh["locked"], [])

    def test_shuffle_keeps_series_together(self):
        series = [goal(f"g{i}", prompt=SCENARIO) for i in range(1, 4)]
        other = [goal("h1", prompt="另一個情境")] + [mc(f"m{i}") for i in range(1, 5)]
        exam = self.exam(*series, *other)
        for seed in range(30):
            session = S.build_session(exam, shuffle_questions=True, rng=random.Random(seed))
            ids = [e["question"]["id"] for e in session["questions"]]
            start = ids.index("g1")
            self.assertEqual(ids[start:start + 3], ["g1", "g2", "g3"])
            self.assertEqual(sorted(ids), sorted(["g1", "g2", "g3", "h1", "m1", "m2", "m3", "m4"]))

    def test_series_blocks(self):
        entries = [{"question": q} for q in (goal("a"), goal("b"), mc("m"), goal("c"), goal("d", prompt="x"))]
        blocks = S.series_blocks(entries)
        self.assertEqual([[e["question"]["id"] for e in b] for b in blocks], [["a", "b"], ["m"], ["c"], ["d"]])


if __name__ == "__main__":
    unittest.main()
