\version "2.24.0"
% meta: key=G major; style=active; quality=1.00; fallback=no; voice=alto; echo=yes

\header {
  title = "amazing_grace"
  subtitle = "Counter-melody for alto"
  tagline = ##f
}

melody = {
  \clef treble
  \key g \major
  \time 3/4
  \tempo 4 = 80
  \partial 4
  d'4 | g'2 b'8 g' | b'2 a'4 | g'2 e'4 |
  d'2 d'4 | g'2 b'8 g' | b'2 a'8 b' | d''2.~ |
  d''2 b'4 | d''4. b'8 d'' b' | g'2 d'4 | e'4. g'8 g' e' |
  d'2 d'4 | g'2 b'8 g' | b'2 a'4 | g'2.~ |
  g'2 r4
  \bar "|."
}

counter = {
  \clef treble
  \key g \major
  \time 3/4
  \partial 4
  r4 | b c'8 d'4. | e'4 e'8 c' e'4~ | e' d' c' |
  b a8 b4. | c'4 d'8 e'4. | d'4 d'8 g'4. | fis'4 d'8 e' fis' d' |
  g' fis' e' d'4. | b2. | b4 c'8 b4. | g2. |
  b4 a8 b4. | b4 c'8 d'4. | e'4 e'8 fis'4. | g'2.~ |
  g'2 r4
  \bar "|."
}

\score {
  <<
    \new ChordNames \chordmode {
      \set chordChanges = ##t
      \partial 4
      d4 | g2. | e:m | c | d | g | g | d | g | g | g | c | d | g | e:m | c | g
    }
    \new Staff \with { instrumentName = "Melody" } \melody
    \new Staff \with { instrumentName = "Alto" } \counter
  >>
  \layout { }
}
