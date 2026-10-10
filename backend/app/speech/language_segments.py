"""Split a tutor reply into Dutch and English runs for text-to-speech.

Beginner replies mix English explanations with quoted Dutch phrases. Read by a
single Dutch voice, the English comes out with a heavy Dutch accent (and by an
English voice, the Dutch would be mispronounced), so each run is voiced in its
own language.

Detection is a lightweight heuristic: quoted / emphasised spans and sentences
are scored by how many common Dutch vs. English function words they contain.
Chunks with no signal (e.g. "Goedemorgen!") take the language of a neighbour;
quoted chunks with no signal default to Dutch, since that is what the tutor
quotes.
"""
from __future__ import annotations

import re

DUTCH = "nl"
ENGLISH = "en"

# Common words unique to each language (words shared by both, such as "is",
# "in", "we" and "was", are deliberately left out).
_DUTCH_WORDS = frozenset(
    """
    de het een en ik je jij jou jouw u uw hij zij ze wij jullie mijn zijn haar
    niet geen wat hoe waar wie waarom dat dit die deze van voor met op te naar
    maar ook heb hebt heeft ben bent hebben graag goed dank bedankt wel nee ja
    hallo goedemorgen goedemiddag goedenavond doei heet heten gaat kan kunt
    wil wilt moet moeten er om bij als nog dan zo heel fijn leuk prima welkom
    tot ziens alstublieft alsjeblieft geprobeerd woon kom spreek leren lekker
    vandaag morgen gisteren mag zeg zegt zeggen probeer nederlands
    """.split()
)
_ENGLISH_WORDS = frozenset(
    """
    the a an and you your yours i my me are am were it its this that these
    those to of for with on at can could would should will do does did not
    what how where who why say said try means mean meaning word words like
    let let's here there great nice correct correction small sentence phrase
    if want just replace name hello again which also or but so because when
    now next then yes no please thanks thank good well done means instead
    full own say saying english dutch learn
    """.split()
)

# Quoted or emphasised spans: "...", “...”, „...”, *...*
_QUOTED = re.compile(r'"[^"\n]+"|“[^”\n]+”|„[^”“\n]+[”“]|\*[^*\n]+\*')
# Sentence-ish boundaries, keeping the delimiter with the preceding text.
_SENTENCE = re.compile(r"[^.!?:;\n—–]+[.!?:;\n—–]*")
_WORD = re.compile(r"[a-zà-ÿ']+")


def _score(text: str) -> str | None:
    words = _WORD.findall(text.lower())
    nl = sum(w in _DUTCH_WORDS for w in words)
    en = sum(w in _ENGLISH_WORDS for w in words)
    if nl > en:
        return DUTCH
    if en > nl:
        return ENGLISH
    return None


def _chunks(text: str) -> list[tuple[str, bool]]:
    """Split into (chunk, is_quoted) pieces covering all of `text`."""
    pieces: list[tuple[str, bool]] = []
    pos = 0
    for match in _QUOTED.finditer(text):
        pieces.extend((s, False) for s in _SENTENCE.findall(text[pos : match.start()]))
        pieces.append((match.group(), True))
        pos = match.end()
    pieces.extend((s, False) for s in _SENTENCE.findall(text[pos:]))
    return [(s, quoted) for s, quoted in pieces if s.strip()]


def split_by_language(text: str, default: str = DUTCH) -> list[tuple[str, str]]:
    """Return [(language, text), ...] runs, adjacent same-language runs merged."""
    chunks = _chunks(text.replace("**", "*"))
    langs = [_score(chunk) for chunk, _ in chunks]

    for i, (_, quoted) in enumerate(chunks):
        if langs[i] is None and quoted:
            langs[i] = DUTCH
    # Unresolved chunks follow the previous chunk, or else the next one.
    for i in range(len(langs)):
        if langs[i] is None:
            prev = next((langs[j] for j in range(i - 1, -1, -1) if langs[j]), None)
            nxt = next((langs[j] for j in range(i + 1, len(langs)) if langs[j]), None)
            langs[i] = prev or nxt or default

    runs: list[tuple[str, str]] = []
    for (chunk, _), lang in zip(chunks, langs):
        # Markdown emphasis and bullets are not meant to be read aloud.
        spoken = chunk.replace("*", "").replace("\n- ", "\n").strip()
        if not spoken:
            continue
        if runs and runs[-1][0] == lang:
            runs[-1] = (lang, f"{runs[-1][1]} {spoken}")
        else:
            runs.append((lang, spoken))
    return [(lang, t.strip()) for lang, t in runs if t.strip()]
