"""Unit tests for the quizzes admin CRUD (build, clone, delete)."""

from __future__ import annotations

from sqlmodel import Session

from app.domains.quizzes import admin, service


def test_build_quiz_then_score(engine) -> None:
    with Session(engine) as s:
        quiz = admin.create_quiz(s, "x", "X", "X")
        admin.add_dimension(s, quiz.id, "d1", "D1", "D1")
        dim = admin.get_dimensions(s, quiz.id)[0]
        admin.add_question(s, quiz.id, dim.id, "Frage", "Q")
        q = admin.get_questions(s, quiz.id)[0]
        admin.add_option(s, q.id, "Ja", "Yes")  # added first → best (rank 0, weight 1.0)
        admin.add_option(s, q.id, "Nein", "No")  # worst (rank 1, weight 0.0)
        admin.add_tier(s, quiz.id, "Low", "Low", 0, 49)
        admin.add_tier(s, quiz.id, "High", "High", 50, 100)

        yes = next(o for o in admin.get_options(s, q.id) if o.weight == 1.0)
        result = service.score_submission(s, quiz, {q.id: yes.id})

    assert result.overall == 100
    assert result.tier_name == "High"


def test_clone_duplicates_tree_unpublished(engine) -> None:
    with Session(engine) as s:
        quiz = admin.create_quiz(s, "x", "X", "X")
        admin.add_dimension(s, quiz.id, "d", "D", "D")
        clone = admin.clone_quiz(s, quiz.id)

        assert clone is not None
        assert clone.slug == "x-copy"
        assert clone.is_published is False
        assert len(admin.get_dimensions(s, clone.id)) == 1


def test_delete_removes_children(engine) -> None:
    with Session(engine) as s:
        quiz = admin.create_quiz(s, "x", "X", "X")
        admin.add_dimension(s, quiz.id, "d", "D", "D")
        qid = quiz.id
        admin.delete_quiz(s, qid)

        assert admin.get_quiz(s, qid) is None
        assert admin.get_dimensions(s, qid) == []
        assert admin.get_landing(s, qid) is None


# --- Option ranking: weights are derived, never hand-entered ---------------
def _weights_by_rank(options) -> dict[int, float]:
    return {o.score_rank: round(o.weight, 3) for o in options}


def test_added_options_get_evenly_spaced_weights(engine) -> None:
    with Session(engine) as s:
        quiz = admin.create_quiz(s, "x", "X", "X")
        admin.add_dimension(s, quiz.id, "d", "D", "D")
        dim = admin.get_dimensions(s, quiz.id)[0]
        admin.add_question(s, quiz.id, dim.id, "F", "Q")
        q = admin.get_questions(s, quiz.id)[0]
        for label in ("A", "B", "C", "D"):  # best → worst in add order
            admin.add_option(s, q.id, label, label)
        opts = admin.get_options(s, q.id)

    # ranks are 0..n-1 (gap-free) and weights step 1.0 / .667 / .333 / 0.0
    assert sorted(o.score_rank for o in opts) == [0, 1, 2, 3]
    assert _weights_by_rank(opts) == {0: 1.0, 1: 0.667, 2: 0.333, 3: 0.0}


def test_reorder_options_flips_weights(engine) -> None:
    with Session(engine) as s:
        quiz = admin.create_quiz(s, "x", "X", "X")
        admin.add_dimension(s, quiz.id, "d", "D", "D")
        dim = admin.get_dimensions(s, quiz.id)[0]
        admin.add_question(s, quiz.id, dim.id, "F", "Q")
        q = admin.get_questions(s, quiz.id)[0]
        admin.add_option(s, q.id, "best", "best")
        admin.add_option(s, q.id, "worst", "worst")
        ids = [o.id for o in admin.get_options(s, q.id)]

        admin.reorder_options(s, q.id, list(reversed(ids)))
        by_label = {o.label_de: o for o in admin.get_options(s, q.id)}

    assert by_label["worst"].score_rank == 0 and by_label["worst"].weight == 1.0
    assert by_label["best"].score_rank == 1 and by_label["best"].weight == 0.0


def test_move_option_swaps_with_neighbour(engine) -> None:
    with Session(engine) as s:
        quiz = admin.create_quiz(s, "x", "X", "X")
        admin.add_dimension(s, quiz.id, "d", "D", "D")
        dim = admin.get_dimensions(s, quiz.id)[0]
        admin.add_question(s, quiz.id, dim.id, "F", "Q")
        q = admin.get_questions(s, quiz.id)[0]
        for label in ("A", "B", "C"):  # ranks 0,1,2
            admin.add_option(s, q.id, label, label)

        c = next(o for o in admin.get_options(s, q.id) if o.label_de == "C")
        admin.move_option(s, c.id, "up")  # C (rank 2) -> rank 1
        ranks = {o.label_de: o.score_rank for o in admin.get_options(s, q.id)}
        assert ranks == {"A": 0, "B": 2, "C": 1}

        a = next(o for o in admin.get_options(s, q.id) if o.label_de == "A")
        admin.move_option(s, a.id, "up")  # already best — no-op, stays consistent
        ranks2 = {o.label_de: o.score_rank for o in admin.get_options(s, q.id)}
        assert ranks2 == {"A": 0, "B": 2, "C": 1}
        assert sorted(o.score_rank for o in admin.get_options(s, q.id)) == [0, 1, 2]


def test_delete_option_repacks_ranks(engine) -> None:
    with Session(engine) as s:
        quiz = admin.create_quiz(s, "x", "X", "X")
        admin.add_dimension(s, quiz.id, "d", "D", "D")
        dim = admin.get_dimensions(s, quiz.id)[0]
        admin.add_question(s, quiz.id, dim.id, "F", "Q")
        q = admin.get_questions(s, quiz.id)[0]
        for label in ("A", "B", "C"):
            admin.add_option(s, q.id, label, label)
        middle = next(o for o in admin.get_options(s, q.id) if o.label_de == "B")
        admin.delete_option(s, middle.id)
        opts = admin.get_options(s, q.id)

    assert sorted(o.score_rank for o in opts) == [0, 1]  # no gap left behind
    assert _weights_by_rank(opts) == {0: 1.0, 1: 0.0}


# --- Dimension shares: always sum to 100 -----------------------------------
def test_added_dimensions_share_sums_to_100(engine) -> None:
    with Session(engine) as s:
        quiz = admin.create_quiz(s, "x", "X", "X")
        for key in ("a", "b", "c"):
            admin.add_dimension(s, quiz.id, key, key, key)
        weights = [d.weight for d in admin.get_dimensions(s, quiz.id)]

    assert round(sum(weights), 1) == 100.0
    assert all(abs(w - 100 / 3) < 1.0 for w in weights)  # ~equal split


def test_set_dimension_weights_normalises(engine) -> None:
    with Session(engine) as s:
        quiz = admin.create_quiz(s, "x", "X", "X")
        admin.add_dimension(s, quiz.id, "a", "a", "a")
        admin.add_dimension(s, quiz.id, "b", "b", "b")
        dims = admin.get_dimensions(s, quiz.id)
        # raw 30/10 → normalised 75/25 (sum 100)
        admin.set_dimension_weights(s, quiz.id, {dims[0].id: 30.0, dims[1].id: 10.0})
        by_key = {d.key: d.weight for d in admin.get_dimensions(s, quiz.id)}

    assert round(by_key["a"] + by_key["b"], 1) == 100.0
    assert by_key["a"] == 75.0 and by_key["b"] == 25.0


def test_equalize_dimensions_resets_to_equal(engine) -> None:
    with Session(engine) as s:
        quiz = admin.create_quiz(s, "x", "X", "X")
        for key in ("a", "b", "c", "d"):
            admin.add_dimension(s, quiz.id, key, key, key)
        dims = admin.get_dimensions(s, quiz.id)
        admin.set_dimension_weights(s, quiz.id, {dims[0].id: 70.0})  # skew it
        admin.equalize_dimensions(s, quiz.id)
        weights = [d.weight for d in admin.get_dimensions(s, quiz.id)]

    assert weights == [25.0, 25.0, 25.0, 25.0]
