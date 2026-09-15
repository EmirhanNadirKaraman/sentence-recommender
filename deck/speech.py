"""Reading the deck aloud, with models that run on your own machine.

Nothing here talks to a service. A card goes in and one WAV comes out, read
in the order the card is written:

    die Geschichte                                     German voice
    Was kann man aus der Geschichte ... lernen?        German voice
    What can one learn from the history ...            English voice
    die Geschichte means history.                      English voice
    ... and so on for the other sentences

Two voices, because a card is half German and half English and a Piper voice
speaks one language. Read by the German voice, "What can one learn" comes out
as German phonemes wearing English spelling.

`Speaker` is one method wide, so a model of your own drops in beside these
two. `PiperSpeaker` is the one to use for the whole deck: ~60 MB of ONNX,
several times realtime on CPU, and German is among the languages it was
actually trained for. `TransformersSpeaker` loads anything in the VITS family
through `transformers`, which is the seam for weights you have trained --
a local path works wherever a hub id does. Fine-tuning is a different job and
wants a different tool; this only does inference.

Runs are resumable: a card whose WAV already exists is skipped unless asked
otherwise. The deck is long, laptops sleep, and starting again from nothing
after 3,000 files is a worse failure than a slow one.
"""
from __future__ import annotations

import wave
from pathlib import Path
from typing import Callable, Iterable, Protocol

from deck import Card

# German voices that exist and were trained on read speech rather than on
# audiobook drama. Both `medium`, so the two run at one sample rate and their
# audio can be laid end to end without resampling.
DEFAULT_GERMAN = "de_DE-thorsten-medium"
DEFAULT_ENGLISH = "en_US-lessac-medium"
DEFAULT_HF_MODEL = "facebook/mms-tts-deu"

# Long enough to hear the seam, short enough not to feel like a fault.
GAP_AFTER_WORD = 0.7
GAP_AFTER_LINE = 0.35
GAP_BETWEEN_EXAMPLES = 0.6
# Piper's `length_scale` stretches time, so larger is slower.
SLOW_SCALE = 1.35


class Speaker(Protocol):
    """Anything that can turn a line into raw 16-bit mono PCM."""

    name: str
    sample_rate: int

    def pcm(self, text: str, slow: bool = False) -> bytes:
        ...


class PiperSpeaker:
    """One Piper voice, loaded once and reused for the whole deck.

    Downloaded on first use into `voices_dir` and found there afterwards, so
    a second run is offline. Model and config are a pair and both are
    checked: half a download is the state that fails later, in the middle of
    a long job, rather than immediately.
    """

    def __init__(self, voice: str = DEFAULT_GERMAN,
                 voices_dir: Path = Path("data/voices"),
                 use_cuda: bool = False) -> None:
        from piper import PiperVoice                      # noqa: PLC0415
        from piper.download_voices import download_voice  # noqa: PLC0415

        voices_dir.mkdir(parents=True, exist_ok=True)
        model = voices_dir / f"{voice}.onnx"
        if not model.exists() or not model.with_suffix(".onnx.json").exists():
            print(f"downloading voice {voice} …", flush=True)
            download_voice(voice, voices_dir)
        self.name = voice
        self._voice = PiperVoice.load(model, use_cuda=use_cuda)
        self.sample_rate = int(self._voice.config.sample_rate)

    def pcm(self, text: str, slow: bool = False) -> bytes:
        from piper.config import SynthesisConfig          # noqa: PLC0415

        config = SynthesisConfig(length_scale=SLOW_SCALE) if slow else None
        return b"".join(chunk.audio_int16_bytes
                        for chunk in self._voice.synthesize(text, config))


class TransformersSpeaker:
    """A VITS-family model through `transformers` — hub id or local path.

    The hook for weights you produced yourself: `model` is passed straight to
    `from_pretrained`, so a directory written by a fine-tuning run works
    exactly as a hub name does.

    Only the VITS family is handled here, which covers `mms-tts` and anything
    fine-tuned from it. A model with a different architecture -- one that
    generates audio tokens through a codec, say -- needs its own class; that
    is a dozen lines against this shape, and far less confusing than one
    class pretending every architecture is the same.
    """

    def __init__(self, model: str = DEFAULT_HF_MODEL,
                 device: str | None = None) -> None:
        import torch                                      # noqa: PLC0415
        from transformers import AutoTokenizer, VitsModel  # noqa: PLC0415

        if device is None:
            device = ("cuda" if torch.cuda.is_available()
                      else "mps" if torch.backends.mps.is_available()
                      else "cpu")
        self.name = f"{model} on {device}"
        self._torch = torch
        self._device = device
        self._tokenizer = AutoTokenizer.from_pretrained(model)
        self._model = VitsModel.from_pretrained(model).to(device).eval()
        self.sample_rate = int(self._model.config.sampling_rate)

    def pcm(self, text: str, slow: bool = False) -> bytes:
        torch = self._torch
        if slow:
            # VITS reads this as a rate, so smaller is slower — the opposite
            # of Piper's length_scale, which is why neither is exposed raw.
            self._model.speaking_rate = 1.0 / SLOW_SCALE
        else:
            self._model.speaking_rate = 1.0
        inputs = self._tokenizer(text, return_tensors="pt").to(self._device)
        with torch.no_grad():
            waveform = self._model(**inputs).waveform[0]
        # float -1..1 to signed 16-bit, which is what `wave` writes and what
        # every player reads without being told the format.
        clipped = torch.clamp(waveform, -1.0, 1.0)
        return (clipped * 32767).to(torch.int16).cpu().numpy().tobytes()


def _silence(seconds: float, rate: int) -> bytes:
    return b"\x00\x00" * int(seconds * rate)


def lines_for(card: Card,
              slow: bool = False) -> list[tuple[str, bool, bool, float]]:
    """The card as (text, is_german, is_slow, gap_after), in reading order.

    The slow flag belongs here rather than in `speak`, because this is the
    only place that knows which line is a repeat. Decided there instead, the
    first reading and its echo were indistinguishable and both came out slow.

    The meaning is spoken once per sense, exactly as the page prints it: the
    model gives every sentence in a group the same words, so an equal string
    means the sense has not changed and repeating it would say the same thing
    three times.
    """
    out: list[tuple[str, bool, bool, float]] = [
        (card.spoken, True, False, GAP_AFTER_WORD)]
    said_already: str | None = None
    for index, example in enumerate(card.examples):
        out.append((example.text, True, False, GAP_AFTER_LINE))
        if slow and index == 0:
            # The teaching sentence only. A slow repeat of all three doubles
            # a clip that is already eight utterances long.
            out.append((example.text, True, True, GAP_AFTER_LINE))
        if example.translation:
            out.append((example.translation, False, False, GAP_AFTER_LINE))
        if example.means and example.means != said_already:
            out.append((example.means, False, False, GAP_AFTER_LINE))
            said_already = example.means
        if index != len(card.examples) - 1:
            text, german, is_slow, _ = out[-1]
            out[-1] = (text, german, is_slow, GAP_BETWEEN_EXAMPLES)
    return out


def speak(cards: Iterable[Card], german: Speaker, english: Speaker,
          out_dir: Path, overwrite: bool = False, slow: bool = False,
          on_progress: Callable[[int, int, int], None] | None = None,
          every: int = 25,
          require_gloss: bool = True) -> tuple[int, int, int]:
    """Write one WAV per card. Returns (written, skipped, waiting).

    Both voices must agree on a sample rate, because the lines are laid end
    to end as raw PCM. They do when both are Piper `medium` voices; a
    mismatch is refused here rather than producing a file that plays one
    language at the wrong pitch.

    A card with no English yet is left alone rather than read in German
    only, and that is what lets this run beside `gloss-deck` instead of
    after it. The two skip rules would otherwise fight: a German-only clip
    is a file that exists, and a file that exists is skipped forever, so
    every card read early would stay half a card no matter how many times
    the audio was run again. `require_gloss=False` asks for the German-only
    reading deliberately.
    """
    if german.sample_rate != english.sample_rate:
        raise SystemExit(
            f"the two voices disagree on a sample rate — {german.name} at "
            f"{german.sample_rate} against {english.name} at "
            f"{english.sample_rate}. Pick two of the same quality (both "
            "`medium`, say), or the audio needs resampling this does not do.")
    rate = german.sample_rate
    out_dir.mkdir(parents=True, exist_ok=True)
    cards = list(cards)
    written = skipped = waiting = 0
    for index, card in enumerate(cards, 1):
        path = out_dir / f"{card.stem}.wav"
        if require_gloss and not card.glossed and not path.exists():
            waiting += 1
        elif not card.sentence.strip() or (path.exists() and not overwrite):
            # A zero-length WAV plays as silence and gets mistaken for a
            # model that has stopped working.
            skipped += 1
        else:
            body = bytearray()
            for text, is_german, is_slow, gap in lines_for(card, slow):
                voice = german if is_german else english
                body += voice.pcm(text, slow=is_slow)
                body += _silence(gap, rate)
            with wave.open(str(path), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(rate)
                handle.writeframes(bytes(body))
            written += 1
        if on_progress and (index % every == 0 or index == len(cards)):
            on_progress(index, len(cards), written)
    return written, skipped, waiting


def write_manifest(cards: Iterable[Card], path: Path) -> Path:
    """A tab-separated index of the deck, for whatever plays it.

    Tabs rather than commas because the sentences contain commas and nothing
    in this corpus contains a tab. Anki imports this shape directly: the
    `[sound:...]` column is understood as audio, and the rest become fields.
    """
    import csv                                            # noqa: PLC0415

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        out = csv.writer(handle, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
        out.writerow(["position", "word", "sentence", "translation",
                      "means", "audio"])
        for card in cards:
            first = card.examples[0] if card.examples else None
            out.writerow([card.position, card.spoken,
                          first.text if first else "",
                          (first.translation if first else "") or "",
                          (first.means if first else "") or "",
                          f"[sound:{card.stem}.wav]"])
    return path
