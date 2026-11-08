\version "2.24.0"
% meta: key=D minor; style=active; quality=1.00; fallback=no; voice=alto; echo=no

\header {
  title = "scarborough_fair"
  subtitle = "Counter-melody for alto"
  tagline = ##f
}

melody = {
  \clef treble
  \key d \minor
  \time 3/4
  \tempo 4 = 92
  d'2 d'4 | a'2 a'4 | e'4. f'8 e'4 | d'2. |
  r4 a' c'' | d''2 c''4 | a' bes' g' | a'2. |
  r2 d''4 | d''2 d''4 | c''2 a'4 | a' g' f' |
  e' c'2 | d' e'4 | f' e' d' | c'2 r4 |
  d'2 a'4 | g'2 f'4 | e' d' c' | d'2.
  \bar "|."
}

counter = {
  \clef treble
  \key d \minor
  \time 3/4
  bes4 c'8 bes4. | a4 a8 cis'4. | cis'2~ cis'8 a | bes4 c'8 bes a bes |
  c' f'2 e'8 | d'4 f'8 d'4. | cis'2~ cis'8 e' | cis'4 d'8 cis' a cis' |
  d' f' e' d'4. | f'4 f'8 g'4. | a'4 f'8 c'4. | d'2~ d'8 a |
  a2 bes8 a | g4 a8 bes4. | a2~ a8 g | a4 a8 bes c' c' |
  bes4 a8 bes4. | c'4 bes8 g4. | a2~ a8 a | d'2.
  \bar "|."
}

\score {
  <<
    \new ChordNames \chordmode {
      \set chordChanges = ##t
      d2.:m | a | a | d:m | f | d:m | a:7 | a | d:m | d:m | f | d:m | a | d:m | d:m | f | d:m | g:m | a | d:m
    }
    \new Staff \with { instrumentName = "Melody" } \melody
    \new Staff \with { instrumentName = "Alto" } \counter
  >>
  \layout { }
}
