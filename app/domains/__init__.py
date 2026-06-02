"""Domain packages — bounded contexts, auto-discovered by interfaces/*.

Two domains:
- quizzes      quiz configuration + scoring (Quiz, Dimension, Question, …)
- submissions  lead capture + results (Submission, lead pipeline)

Cross-domain coupling is forbidden (import-linter independence contract):
submissions references a quiz only by string FK + copied scores, never by
importing `app.domains.quizzes`.
"""
