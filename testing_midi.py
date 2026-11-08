"""testing_midi.py — TESTING ONLY. Not part of the app.

Writes MIDI files (via `mido`) so you can listen to a melody and its counter-melody
while developing. Used by `python counter.py ... --midi`. The real app never imports this.
"""
from __future__ import annotations

from lily import Meter, Note


def write_midi(path: str, tracks: list[tuple[list[Note], int, str]], qpm: float, meter: Meter) -> None:
    """Write notes to a MIDI file (one track per voice) with mido."""
    import mido
    tpb = 480
    mid = mido.MidiFile(ticks_per_beat=tpb)
    meta = mido.MidiTrack()
    meta.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(qpm), time=0))
    meta.append(mido.MetaMessage("time_signature", numerator=meter.num, denominator=meter.den, time=0))
    mid.tracks.append(meta)
    for ch, (notes, program, name) in enumerate(tracks):
        tr = mido.MidiTrack()
        tr.append(mido.MetaMessage("track_name", name=name, time=0))
        tr.append(mido.Message("program_change", channel=ch, program=program, time=0))
        evs = []
        for n in notes:
            if n.midi is None:
                continue
            on, off = round(n.start * tpb), round(n.end * tpb) - 2
            evs.append((on, 1, mido.Message("note_on", channel=ch, note=n.midi, velocity=80)))
            evs.append((off, 0, mido.Message("note_off", channel=ch, note=n.midi, velocity=0)))
        evs.sort(key=lambda e: (e[0], e[1]))
        now = 0
        for tick, _o, msg in evs:
            tr.append(msg.copy(time=tick - now))
            now = tick
        mid.tracks.append(tr)
    mid.save(path)
