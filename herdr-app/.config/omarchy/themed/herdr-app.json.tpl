{
  "background": "{{ background }}",
  "foreground": "{{ foreground }}",
  "selection": "{{ selection_background }}",
  "cursor": "{{ bright_foreground }}",
  "ansi": [
    "{{ background }}", "{{ red }}", "{{ green }}", "{{ yellow }}",
    "{{ blue }}", "{{ magenta }}", "{{ cyan }}", "{{ foreground }}",
    "{{ muted }}", "{{ bright_red }}", "{{ bright_green }}", "{{ bright_yellow }}",
    "{{ bright_blue }}", "{{ bright_magenta }}", "{{ bright_cyan }}", "{{ bright_foreground }}"
  ],
  "colors": {
    "canvas": "{{ mix background foreground 2% }}b3",
    "chrome": "{{ mix background foreground 4% }}b3",
    "surface": "{{ mix background foreground 7% }}",
    "popover": "{{ mix background foreground 9% }}",
    "raised": "{{ mix background foreground 11% }}",
    "hover": "{{ mix background foreground 13% }}",
    "selected": "{{ mix background accent 24% }}",
    "border": "{{ mix background foreground 14% }}",
    "input": "{{ mix background foreground 26% }}",
    "muted": "{{ mix background foreground 72% }}",
    "dim": "{{ mix background foreground 48% }}",
    "accent": "{{ accent }}",
    "accent_foreground": "{{ background }}",
    "solid": "{{ accent }}",
    "solid_foreground": "{{ background }}",
    "working": "{{ yellow }}",
    "blocked": "{{ red }}",
    "done": "{{ green }}",
    "idle": "{{ mix background foreground 40% }}"
  }
}
