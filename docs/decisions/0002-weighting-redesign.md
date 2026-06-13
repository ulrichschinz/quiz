# 0002 — Gewichtungs-Redesign: Rangfolge + 100%-Anteile

Status: beschlossen (2026-06-11), noch nicht umgesetzt.

## Problem

Zwei verschiedene Konzepte heißen im Datenmodell und Admin-UI beide „Gewicht":

- **Antwort-Option** `weight` (float 0.0–1.0) = Anteil am Frage-Maximum
  (`app/domains/quizzes/models.py`).
- **Dimension** `weight` (float, unbeschränkt, Default 1.0) = relatives
  Roll-up-Gewicht, in `scoring.py` per Summe normalisiert.

Folgen: inkonsistente Semantik/Ranges, Dubletten möglich (zweimal 0 bei vier
Antworten), kein erzwungenes Maximum, freie Floats ohne Führung im UI.

## Entscheidung

Ziel: maximal nutzerfreundlich, **fehlerunmöglich**, sinnvolle Defaults,
Auto-Rebalancing statt Handarbeit.

### 1. Antwort-Optionen: Rangfolge statt Zahlen

- Der Admin ordnet die Optionen einer Frage per **Drag & Drop von best nach
  schlecht** (Scoring-Rangfolge, getrennt von der Anzeige-Reihenfolge im
  Player!).
- Die Anteile werden automatisch abgeleitet:
  `share = (n − 1 − rank) / (n − 1)` — bei 4 Optionen: 100 % / 66 % / 33 % / 0 %.
  Sonderfall `n == 1`: share = 1.0.
- Strukturell unmöglich: doppelte Werte, fehlendes Maximum, Werte außerhalb
  des Bereichs.
- UI-Begriff: **„Antwort-Rangfolge"** (nicht mehr „Gewicht").

### 2. Dimensionen: Prozent-Anteile, Summe immer 100 %

- Pro Dimension ein **Prozent-Slider**; die Summe ist immer exakt 100 %.
  Verschiebt man einen Slider, rebalancieren sich die übrigen proportional
  (JS im Admin).
- **„Alle gleich verteilen"**-Button; Gleichverteilung ist auch der Default
  beim Anlegen.
- UI-Begriff: **„Themen-Anteil (%)"**.
- Backend-Validierung: Summe = 100 (±Rundungstoleranz, Server gleicht
  Rundungsreste auf der größten Dimension aus).

### 3. Live-Vorschau

Im Quiz-Editor eine kleine Vorschau, die für ein Beispiel-Antwortprofil
(z. B. „alles beste Antwort" / „alles mittlere") den resultierenden Score
und das Tier zeigt — Änderungen an Rangfolge/Anteilen wirken sofort sichtbar.

## Technische Umsetzung

Blast-Radius klein halten — die Scoring-Mathematik in `scoring.py` kann
weitgehend bleiben:

- **Option:** neues Feld `score_rank` (int, 0 = beste; unique je Frage) als
  Quelle der Wahrheit. `weight` bleibt als persistiertes, **abgeleitetes**
  Feld; der Service berechnet es beim Speichern aus der Rangfolge neu →
  `scoring.py` und kopierte Scores in `submissions` bleiben unberührt.
- **Dimension:** `weight` speichert künftig den Prozentwert (z. B. 40.0).
  Da `scoring.py` ohnehin per Summe normalisiert, ist keine
  Scoring-Änderung nötig — nur UI + Validierung (Summe 100).
- **Migration (Alembic):** bestehende Optionen nach `weight` absteigend
  sortieren (Ties: bisherige Position) → `score_rank` vergeben, `weight`
  daraus neu ableiten. Dimensionsgewichte je Quiz auf 100 % normalisieren.
- **Admin-UI** (`templates/admin/quiz_edit.html` + `static/quiz/`):
  Drag & Drop-Rangliste je Frage, 100%-Slider-Gruppe je Quiz mit
  Auto-Rebalance, „Alle gleich"-Button, Live-Vorschau. Begriffe wie oben.

Edit-Reihenfolge (Domain-Konvention): `models.py → schemas.py → service.py →
interfaces → tests`. Navigation vorab über `python -m codeindex`.
Akzeptanz: `make verify` grün.
