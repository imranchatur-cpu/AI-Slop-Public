"""
score.py: score your own writing with EditLens on an ordinary CPU.

EditLens (Pangram Labs, ICLR 2026) gives text a score from 0 to 1:
0 = written by a person, 1 = written by a model, in between = the extent of
AI editing. This script loads Pangram's Llama-3.2-3B release, splits long
pieces into ~300-word sections, and scores each one. No graphics card needed.

Usage (with the Python inside .venv):
  python score.py draft.md                      whole text (first ~750 words)
  python score.py --text "Paste a paragraph"
  python score.py --sections draft.md           one score per section, with line numbers
  python score.py --sections draft.docx --json results.json

Reads .txt, .md, .docx (Word) and .pptx (PowerPoint). For PDFs or anything
else, save the text as .txt first, or let Claude convert it (see the skill).

Environment variables (all optional):
  EDITLENS_BASE_MODEL   base model repo (default meta-llama/Llama-3.2-3B)
  HF_HOME               where Hugging Face stores downloads (~6 GB)

Licence: CC BY-NC-SA 4.0. Non-commercial use only. Contains code adapted from
https://github.com/pangramlabs/EditLens (CC BY-NC-SA 4.0). See LICENSE.md.
"""

import argparse
import json
import os
import re
import sys
import warnings
import zipfile
from xml.etree import ElementTree as ET

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
warnings.filterwarnings("ignore", category=FutureWarning)

ADAPTER = "pangram/editlens_Llama-3.2-3B"
BASE = os.environ.get("EDITLENS_BASE_MODEL", "meta-llama/Llama-3.2-3B")
N_BUCKETS = 4
MAX_LENGTH = 1024  # tokens the model reads, roughly 750 words

# Sections aim for ~300 words: the model is unreliable on very short text and
# only reads 1024 tokens at a time.
MIN_WORDS, TARGET_WORDS, MAX_WORDS = 120, 300, 450

BANDS = ["human", "light AI edit", "heavy AI edit", "AI-generated"]


def band_for(score):
    """Approximate band from the 0-1 score (quartiles). Not Pangram's thresholds."""
    return BANDS[min(3, int(score * 4))]


# --------------------------------------------------------------------------
# Text cleaning, adapted from EditLens scripts/preprocess.py (CC BY-NC-SA 4.0)
# --------------------------------------------------------------------------
BOILERPLATE_STARTS = ["Sure", "Here", "Abstract", "Title", "I'm happy to help", "Certainly"]


def clean_text(text):
    import emoji

    text = emoji.demojize(text)
    if "</think>" in text:
        text = text.split("</think>")[1].strip()
    paragraphs = [p for p in text.split("\n") if p.strip()]
    if paragraphs:
        first = emoji.replace_emoji(re.sub(r"^[^a-zA-Z0-9]*", "", paragraphs[0]), "")
        if any(first.startswith(s) for s in BOILERPLATE_STARTS) and len(paragraphs) > 1:
            text = "\n".join(paragraphs[1:])
    return re.sub(r"\s+", " ", text.lower()).strip()


# --------------------------------------------------------------------------
# Reading files: text, Markdown, Word, PowerPoint (standard library only)
# --------------------------------------------------------------------------
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def read_docx(path):
    """Paragraph text from a Word file. Headings become Markdown headings.
    Deleted tracked changes and comments are left out."""
    root = ET.fromstring(zipfile.ZipFile(path).read("word/document.xml"))
    out = []
    for p in root.iter(W + "p"):
        parts = []
        for node in p.iter():
            if node.tag == W + "t":
                parts.append(node.text or "")
            elif node.tag == W + "tab":
                parts.append(" ")
        line = "".join(parts).strip()
        if not line:
            continue
        style = p.find(f"{W}pPr/{W}pStyle")
        level = re.match(r"Heading(\d)", style.get(W + "val")) if style is not None else None
        out.append(("#" * int(level.group(1)) + " " if level else "") + line)
    return "\n\n".join(out)


def read_pptx(path):
    """Text from each slide, in slide order, one block per slide."""
    z = zipfile.ZipFile(path)
    slides = sorted(
        (n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
        key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[1]).group(1)),
    )
    P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
    skip = {"sldNum", "dt", "ftr"}  # slide numbers, dates, footers
    blocks = []
    for name in slides:
        root = ET.fromstring(z.read(name))
        paras = []
        for sp in root.iter(P + "sp"):
            ph = sp.find(f"{P}nvSpPr/{P}nvPr/{P}ph")
            if ph is not None and ph.get("type") in skip:
                continue
            for p in sp.iter(A + "p"):
                t = "".join(r.text or "" for r in p.iter(A + "t")).strip()
                if t:
                    paras.append(t)
        if paras:
            blocks.append("\n".join(paras))
    return "\n\n".join(blocks)


def read_file(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        return read_docx(path)
    if ext == ".pptx":
        return read_pptx(path)
    if ext in (".pdf", ".doc", ".ppt", ".rtf", ".odt"):
        sys.exit(f"{path}: {ext} is not supported. Save it as .txt, .md or .docx first.")
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        return fh.read()


# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------
def load():
    import torch
    from peft import PeftModel
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    from transformers.utils import logging as hf_logging

    hf_logging.set_verbosity_error()
    hf_logging.disable_progress_bar()

    class NormedLinear(torch.nn.Module):
        """Score head used by EditLens (from scripts/train.py)."""

        def __init__(self, hidden_size, num_labels, dtype=None):
            super().__init__()
            self.norm = torch.nn.LayerNorm(hidden_size, dtype=dtype)
            self.linear = torch.nn.Linear(hidden_size, num_labels, bias=False, dtype=dtype)

        def forward(self, x):
            return self.linear(self.norm(x))

    try:
        tok = AutoTokenizer.from_pretrained(ADAPTER)  # Pangram ships its training tokenizer
        tok.pad_token = tok.eos_token
        tok.padding_side = "left"
        base = AutoModelForSequenceClassification.from_pretrained(
            BASE, num_labels=N_BUCKETS, dtype=torch.bfloat16
        )
    except Exception as e:  # most often: gated access not yet granted, or not signed in
        msg = str(e)
        if "gated" in msg.lower() or "restricted" in msg.lower() or "401" in msg or "403" in msg:
            sys.exit(
                "Hugging Face refused the download.\n"
                f"  1. Accept the terms at https://huggingface.co/{ADAPTER}\n"
                f"  2. Request access at https://huggingface.co/{BASE} (a person reviews it)\n"
                "  3. Sign in: hf auth login\n"
                f"Details: {msg.splitlines()[0]}"
            )
        raise
    base.config.pad_token_id = tok.pad_token_id
    base.score = NormedLinear(base.config.hidden_size, N_BUCKETS, dtype=torch.bfloat16)
    model = PeftModel.from_pretrained(base, ADAPTER)  # loads the trained score head too
    model.eval()
    return tok, model


def score(tok, model, text):
    import torch

    with torch.inference_mode():
        enc = tok(clean_text(text), truncation=True, max_length=MAX_LENGTH, return_tensors="pt")
        probs = torch.softmax(model(**enc).logits.float()[0], dim=-1)
    s = (probs @ torch.arange(N_BUCKETS, dtype=torch.float)).item() / (N_BUCKETS - 1)
    n = int(enc["input_ids"].shape[1])
    return {
        "score": round(s, 4),
        "band": band_for(s),
        "probs": [round(p, 4) for p in probs.tolist()],
        "tokens": n,
        "truncated": n >= MAX_LENGTH,
    }


# --------------------------------------------------------------------------
# Sections
# --------------------------------------------------------------------------
def words(s):
    return len(re.findall(r"\b\w+\b", s))


def strip_markdown_noise(block):
    """Drop what isn't prose: images, bare links, HTML comments, rules, [IMAGE ...] placeholders."""
    block = re.sub(r"<!--.*?-->", "", block, flags=re.S)
    keep = []
    for line in block.splitlines():
        t = line.strip()
        if (
            re.fullmatch(r"!\[[^\]]*\]\([^)]*\)", t)
            or re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", t)
            or re.fullmatch(r"https?://\S+", t)
            or re.fullmatch(r"\[(IMAGE|LINK|CONFIRM)\b[^\]]*\]", t)
        ):
            continue
        keep.append(re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line))
    return "\n".join(keep).strip()


def split_sections(text):
    """~300-word sections on paragraph boundaries, with 1-based line ranges."""
    lines = text.splitlines()
    start = 0
    if lines and lines[0].strip() == "---":  # YAML front matter
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                start = i + 1
                break

    paras, buf, first = [], [], None
    for i in range(start, len(lines) + 1):
        line = lines[i] if i < len(lines) else ""
        if line.strip() == "" or i == len(lines):
            if buf:
                body = strip_markdown_noise("\n".join(buf))
                if body:
                    paras.append((first + 1, i, body))
                buf, first = [], None
        else:
            first = i if first is None else first
            buf.append(line)

    sections, cur = [], []

    def flush():
        if cur:
            sections.append({
                "line_start": cur[0][0],
                "line_end": cur[-1][1],
                "text": "\n\n".join(p[2] for p in cur),
            })

    for p in paras:
        n = sum(words(c[2]) for c in cur)
        heading = p[2].lstrip().startswith("#")
        if cur and (
            (heading and n >= MIN_WORDS)
            or n >= TARGET_WORDS
            or (n + words(p[2]) > MAX_WORDS and n >= MIN_WORDS)
        ):
            flush()
            cur = []
        cur.append(p)
    flush()

    if len(sections) > 1 and words(sections[-1]["text"]) < MIN_WORDS:
        last = sections.pop()
        sections[-1]["text"] += "\n\n" + last["text"]
        sections[-1]["line_end"] = last["line_end"]
    for i, s in enumerate(sections, 1):
        s["index"] = i
        s["words"] = words(s["text"])
    return sections


def run_sections(tok, model, name, text):
    sections = split_sections(text)
    total = sum(s["words"] for s in sections) or 1
    for s in sections:
        s.update(score(tok, model, s["text"]))
        print(
            f"  [{s['index']:>2}] lines {s['line_start']}-{s['line_end']}  "
            f"{s['words']:>4}w  score={s['score']:.3f}  {s['band']}",
            file=sys.stderr,
        )
    overall = sum(s["score"] * s["words"] for s in sections) / total
    if total < MIN_WORDS:
        print(f"  note: only {total} words; scores on short text are unreliable", file=sys.stderr)
    print(f"{name}: overall={overall:.3f} ({band_for(overall)}) across {len(sections)} sections, {total} words")
    return {
        "source": name,
        "overall_score": round(overall, 4),
        "overall_band": band_for(overall),
        "max_section_score": max((s["score"] for s in sections), default=None),
        "total_words": total,
        "sections": sections,
    }


def main():
    ap = argparse.ArgumentParser(description="Score your own writing with EditLens.")
    ap.add_argument("files", nargs="*", help=".txt .md .docx .pptx files, or - for stdin")
    ap.add_argument("--text", help="score this string directly")
    ap.add_argument("--sections", action="store_true", help="score each ~300-word section")
    ap.add_argument("--json", help="write full results to this JSON file")
    ap.add_argument("--dump-text", action="store_true", help="print the extracted text and exit (no model)")
    args = ap.parse_args()

    items = []
    if args.text:
        items.append(("--text", args.text))
    for f in args.files:
        items.append(("stdin", sys.stdin.read()) if f == "-" else (f, read_file(f)))
    if not items:
        ap.error("give one or more files, - for stdin, or --text")

    if args.dump_text:
        for _, text in items:
            sys.stdout.reconfigure(encoding="utf-8")
            print(text)
        return

    print("Loading model (the first run downloads about 6 GB)...", file=sys.stderr)
    tok, model = load()
    results = []
    for name, text in items:
        if args.sections:
            results.append(run_sections(tok, model, name, text))
        else:
            r = score(tok, model, text)
            r["source"] = name
            results.append(r)
            note = " (only the first ~750 words were read; use --sections)" if r["truncated"] else ""
            print(f"{name}: score={r['score']:.3f} ({r['band']}){note}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(results[0] if len(results) == 1 else results, fh, indent=2, ensure_ascii=False)
        print(f"Wrote {args.json}", file=sys.stderr)


if __name__ == "__main__":
    main()
