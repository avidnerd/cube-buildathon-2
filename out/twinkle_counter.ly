\version "2.24.0"
% meta: key=C major; style=calm; quality=0.98; fallback=no; voice=alto; echo=no

\header {
  title = "twinkle"
  subtitle = "Counter-melody for alto"
  tagline = ##f
}

melody = {
  \clef treble
  \key c \major
  \time 4/4
  \tempo 4 = 100
  c'4 c' g' g' | a' a' g'2 | f'4 f' e' e' | d' d' c'2 |
  g'4 g' f' f' | e' e' d'2 | g'4 g' f' f' | e' e' d'2 |
  c'4 c' g' g' | a' a' g'2 | f'4 f' e' e' | d' d' c'2
  \bar "|."
}

counter = {
  \clef treble
  \key c \major
  \time 4/4
  e''2 d'' | c'' e''4 b' | c''2 c'' | d'' e''4 c'' |
  b'2 d'' | g' a'4 a' | b'2 d'' | c'' d''4 b' |
  e''2 d'' | c'' e''4 e'' | a'2 g' | b' c''
  \bar "|."
}

\score {
  <<
    \new ChordNames \chordmode {
      \set chordChanges = ##t
      c1 | f2 c | f c | g c | g1:7 | c2 d:m | g1:7 | c2 g | c1 | f2 c | f c | g c
    }
    \new Staff \with { instrumentName = "Melody" } \melody
    \new Staff \with { instrumentName = "Alto" } \counter
  >>
  \layout { }
}
