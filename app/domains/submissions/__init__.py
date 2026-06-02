"""Submissions domain — lead capture + results.

A Submission row IS the durable lead: the answers, the computed scores, the
resolved tier and the captured contact details, plus the pipeline audit trail
(local / CRM / email). It references a quiz only by a soft `quiz_id` + copied
`quiz_slug`/`tier_name` and the persisted scores — never by importing the
quizzes domain (import-linter independence).
"""
