"""Quizzes domain — quiz configuration + scoring.

Owns everything an admin configures: the quiz itself, its dimensions,
questions and answer options (with scoring weights), the result tiers
("Auswertungen") and the landing/result-page copy. Pure config + a pure
scoring function (`scoring.py`); it captures no leads (that is `submissions`).
"""
