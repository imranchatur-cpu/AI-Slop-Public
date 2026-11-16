---
name: editlens
description: Score your own writing for how much it reads as AI-edited, using the local EditLens model (Pangram Labs, Llama-3.2-3B release, runs on CPU), then suggest edits section by section and save the draft, scores and report into one folder. Use when the user pastes or points to a draft, post, document or presentation and says "editlens", "check this for AI", "AI check", "slop check", "score this", or says "rescore" after editing a saved draft.
---

# EditLens: score, suggest, save

EditLens gives a passage a score from 0 (written by a person) to 1 (written by
a model). Values in between measure how much AI editing it shows. The point is
to find where a draft sounds generic, so the writer can put their own
knowledge back in. It is not a tool for disguising AI text, and a score is not
proof about anyone's writing.

## Paths

`setup.ps1` fills these in. If you installed by hand, replace them yourself.

| What | Where |
|---|---|
| Python | `{{PYTHON}}` |
| Scorer | `{{KIT_DIR}}/score.py` |
| Runs | `{{RUNS_DIR}}/<YYYY-MM-DD> <Short Title>/` |

## Flow

### 1. Get the text into one file

- **Pasted text:** create the run folder and write the paste, unchanged, to
  `draft.md`. Name the folder from the heading or first line (3 to 6 words,
  no characters Windows forbids in file names).
- **A .txt, .md, .docx or .pptx file:** score it where it is. Do not copy it.
  Put the outputs in an `editlens` folder next to it.
- **Anything else** (PDF, Google Doc, a web page): read it, write its text to
  `draft.md` in a new run folder, and tell the user that `draft.md` is now the
  copy to edit.

### 2. Score it

```
"{{PYTHON}}" "{{KIT_DIR}}/score.py" --sections "<file>" --json "<run folder>/editlens.json"
```

Allow up to 10 minutes. Loading takes about 15 seconds, then a few seconds per
section. The first run ever also downloads about 6 GB. Under about 120 words
the model is unreliable, so say so for short text.

If it fails with "Hugging Face refused the download", the user has not been
granted access yet or is not signed in. Relay the steps it prints.

### 3. Suggest, in chat first

Read `editlens.json`. Flag every section scoring **0.5 or higher**. If none
do, look at the two highest and say the draft reads as the writer's own.

For each flagged section, name what is likely driving the score. Common
signs: generic framing with no named company, number or date; tidy lists of
three; "not X, but Y" turns; signposting ("Here's the thing", "Let's dive
in"); hedged abstractions; every sentence the same length.

Give 2 to 4 suggestions per flagged section, each one of:

- **Cut:** a phrase or sentence to delete, quoted exactly.
- **Ask:** a question only the writer can answer, which would replace a
  generic line with a specific one ("Which client was this? What did it cost
  them?").
- **Tighten:** a short rewrite of one sentence, only where a cut or reorder
  will not do it.

Never rewrite whole paragraphs. Text you write is AI text, so a rewrite
raises the score. The writer writes the replacement.

Show in chat: the overall score and band, a table of sections (number, lines,
score, band, first few words), then the suggestions.

### 4. Save the report

Write `editlens-report.md` in the run folder:

```
# EditLens: <title>
Scored <date> · overall <score> (<band>) · <n> sections · <words> words

| # | Lines | Words | Score | Band | Starts |
|---|---|---|---|---|---|

## Section <n>, lines <a>–<b>, score <score>
> <first ~25 words of the section>…

- **Cut:** …
- **Ask:** …

## Rescore history
| Date | Overall | Flagged sections |
```

Tell the user the folder path and which file to edit. Line numbers refer to
the text file; for .docx and .pptx they refer to the extracted text, so quote
the opening words of each section as well.

### 5. Rescore

On "rescore", run step 2 again on the same file, append a row to "Rescore
history" and a short before-and-after by section. Keep the earlier
suggestions.

## Limits to state when relevant

- Bands (0–0.25 human, 0.25–0.5 light AI edit, 0.5–0.75 heavy AI edit,
  0.75–1 AI-generated) are an approximate split of the score, not Pangram's
  published thresholds.
- This is the smallest model Pangram released. Their paid product at
  pangram.com is stronger.
- Quotes, code and lists score oddly. A flagged section that is mostly quoted
  material is likely noise.
- Licence: CC BY-NC-SA 4.0. Non-commercial use only.
