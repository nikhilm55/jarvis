"""Text pools for the wake-word pipeline: commands, sound-alikes and general sentences."""

from __future__ import annotations

import random
import re
from collections.abc import Iterable
from pathlib import Path

# Short spoken commands that follow "Jarvis,". Written for this pipeline. The first model's list shared three
# commands with the M0a set ("stop", "take a screenshot"); they are removed here, and
# check_holdout.py now compares commands, so the overlap cannot come back unnoticed.
COMMANDS = [
    "what's on my calendar tomorrow", "set a timer for twelve minutes", "turn the brightness up",
    "read me the latest email", "start a new document", "mute the microphone", "pause the music",
    "what time is my next meeting", "search for flight prices to Berlin",
    "switch to the terminal", "summarise this page", "add milk to the shopping list",
    "play something relaxing", "turn off the lights in the study", "how's the weather looking",
    "open the project folder", "remind me to stretch at four", "dictate a note to myself",
    "go to the next slide", "increase the font size", "send the report to Anna", "check my battery",
    "launch the browser", "close this window", "what did I miss", "lower the volume a bit",
    "compose a reply", "show me my downloads", "restart the build", "find the invoice from March",
    "call the office", "save this file", "undo that", "scroll down", "zoom in", "read it again",
    "start the stopwatch", "what's the date today", "join the stand-up",
    "copy the last line", "lock the screen", "bookmark this", "translate that to French",
    "snooze the alarm", "who is calling", "convert ten miles to kilometres", "wake me at six",
    "list my open tasks", "new tab please", "never mind", "yes", "go ahead", "thanks",
]  # fmt: skip

# Adversarial sound-alikes (R72): real names and words a first-word gate could mistake for "Jarvis". Spellings that
# are only mispronunciations of it (Jervis, Darvis, Jarvik, ...) are left out on purpose: the gate accepts them too.
# The first model also trained on the eight M0a sound-alike words (Travis, Davis, Service, Nervous, Harvest, Jars,
# Elvis, Garvey); they are gone so M0a measures words the model has not heard. Kept from R72: Marvin, Paris, Harris.
SOUND_ALIKES = [
    "Marvin", "Paris", "Harris", "Harvey", "Mavis", "Jarred", "Curtis", "Gervais", "Purvis", "Servers", "Carvers", "Charles",
    "Larvae", "Jarrett", "Jessica", "Jargon", "Jasper", "Javier", "Jolly", "Dervish", "Nervy", "Carve us",
    "Charge us", "Targets", "Artists", "Parvati", "Mars", "Gargoyles", "Marbles", "Harpers", "Carpets",
]  # fmt: skip

# Short everyday utterances, so the model also hears the speech of a normal room.
CASUAL = [
    "Could you forward me the notes from this morning", "I think the deploy went out twice",
    "Let's meet by the window around noon", "The customer asked for a different colour scheme",
    "Has anybody seen my charger", "The wifi in this room is terrible", "We need a second pair of eyes on that",
    "Hold on, I'm just finishing a sentence", "The train was packed again today", "Pass me that pen, please",
    "What time does the shop close", "Okay", "Right then", "Hey, are you free", "Hello", "Good morning everyone",
    "See you tomorrow", "Alexa, what's the time", "Hey Siri, call home", "Okay Google, play some jazz",
    "Thank you", "That makes sense", "I'll look into it", "Sorry, could you say that again",
]  # fmt: skip

PUNCT = ["", ".", ",", "!", "?"]
_ASCII = re.compile(r"^[A-Za-z0-9 ,.'?!-]+$")


def librispeech_sentences(root: Path, *, seed: int = 0) -> list[tuple[str, str]]:
    """(speaker, sentence) from LibriSpeech dev-clean: 5-22 words, shuffled, never 'jarvis'."""
    out: list[tuple[str, str]] = []
    for trans in sorted(root.rglob("*.trans.txt")):
        for line in trans.read_text(encoding="utf-8").splitlines():
            name, _, text = line.partition(" ")
            words = text.lower().split()
            if 5 <= len(words) <= 22 and "jarvis" not in text.lower():
                sentence = " ".join(words)
                if _ASCII.match(sentence):
                    out.append((name.split("-")[0], sentence[0].upper() + sentence[1:] + "."))
    random.Random(seed).shuffle(out)
    return out


def val_speaker_ids(speakers: Iterable[str]) -> set[str]:
    """Every fifth LibriSpeech speaker (sorted) is validation; augment.py uses the same rule for real audio."""
    return set(sorted(set(speakers))[::5])


def split_every(items: list[str], n: int) -> tuple[list[str], list[str]]:
    """(train, val): every n-th item is validation; the lists share nothing."""
    return [x for i, x in enumerate(items) if i % n], [x for i, x in enumerate(items) if i % n == 0]
