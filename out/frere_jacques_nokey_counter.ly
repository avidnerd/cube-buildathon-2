\version "2.24.0"
% meta: key=F major; style=calm; quality=0.90; fallback=no; voice=alto; echo=no

\header {
  title = "frere_jacques_nokey"
  subtitle = "Counter-melody for alto"
  tagline = ##f
}

melody = {
  \clef treble
  \key f \major
  \time 4/4
  \tempo 4 = 112
  f'4 g' a' f' | f' g' a' f' | a' bes' c''2 | a'4 bes' c''2 |
  c''8 d'' c'' bes' a'4 f' | c''8 d'' c'' bes' a'4 f' | f' c' f'2 | f'4 c' f'2
  \bar "|."
}

counter = {
  \clef treble
  \key f \major
  \time 4/4
  a2 c' | a c' | c' a4 bes | c'2 a4 a |
  c'1 | c' | a2 a4 bes | a2 a
  \bar "|."
}

\score {
  <<
    \new ChordNames \chordmode {
      \set chordChanges = ##t
      f1 | f | f | f | f | f | f | f
    }
    \new Staff \with { instrumentName = "Melody" } \melody
    \new Staff \with { instrumentName = "Alto" } \counter
  >>
  \layout { }
}
