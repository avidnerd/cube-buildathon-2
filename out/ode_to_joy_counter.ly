\version "2.24.0"
% meta: key=D major; style=calm; quality=1.00; fallback=no; voice=alto; echo=no

\header {
  title = "ode_to_joy"
  subtitle = "Counter-melody for alto"
  tagline = ##f
}

melody = {
  \clef treble
  \key d \major
  \time 4/4
  \tempo 4 = 108
  fis'4 fis' g' a' | a' g' fis' e' | d' d' e' fis' | fis'4. e'8 e'2 |
  fis'4 fis' g' a' | a' g' fis' e' | d' d' e' fis' | e'4. d'8 d'2
  \bar "|."
}

counter = {
  \clef treble
  \key d \major
  \time 4/4
  d'2 e' | d' a | b a | d' cis'4 cis' |
  a2 e' | d' a | b a | cis' d'
  \bar "|."
}

\score {
  <<
    \new ChordNames \chordmode {
      \set chordChanges = ##t
      d2 a:7 | d1 | d | d2 a | d a:7 | d1 | d | a2 d
    }
    \new Staff \with { instrumentName = "Melody" } \melody
    \new Staff \with { instrumentName = "Alto" } \counter
  >>
  \layout { }
}
