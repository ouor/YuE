"""Sheet-music view: abcjs renders the ABC score and plays it back in the browser."""
from __future__ import annotations

import gradio as gr

ABCJS = "https://cdnjs.cloudflare.com/ajax/libs/abcjs/6.7.1/abcjs-basic-min.js"
ABCJS_AUDIO_CSS = "https://cdn.jsdelivr.net/npm/abcjs@6.7.1/abcjs-audio.css"

HEAD = f'<script src="{ABCJS}"></script><link rel="stylesheet" href="{ABCJS_AUDIO_CSS}">'

TEMPLATE = """
<div class="score-view">
  <div class="score-empty">${empty}</div>
  <div class="score-audio"></div>
  <div class="score-sheet"></div>
</div>
"""

# The ABC text is passed as the component value and never interpolated into the
# template, so user-edited scores cannot inject markup.
JS = """
let controller = null, lastWidth = 0;
function draw(attempt) {
  const abc = (props.value || '').trim();
  const sheet = element.querySelector('.score-sheet');
  const audio = element.querySelector('.score-audio');
  const empty = element.querySelector('.score-empty');
  if (controller) { try { controller.pause(); } catch (e) {} }
  if (!abc) { sheet.innerHTML = ''; audio.innerHTML = ''; empty.style.display = 'block'; return; }
  empty.style.display = 'none';
  if (!window.ABCJS) { if ((attempt || 0) < 50) setTimeout(() => draw((attempt || 0) + 1), 200); return; }
  // Reflow to the available width (2 bars per line on phones) instead of shrinking the notes.
  const width = sheet.clientWidth;
  if (!width) return;                        // hidden tab: the resize observer draws it when shown
  lastWidth = width;
  // Voice names ("Vocal Melody") take a third of a phone's width; drop them there.
  const source = width < 560 ? abc.replace(/ (?:s?nm|name)="[^"]*"/g, '') : abc;
  const tunes = ABCJS.renderAbc(sheet, source, {
    add_classes: true, paddingtop: 4, paddingbottom: 4, paddingleft: 4, paddingright: 4,
    staffwidth: Math.max(240, width - 24),
    wrap: { minSpacing: 1.6, maxSpacing: 2.8, preferredMeasuresPerLine: width < 560 ? 2 : 4 },
  });
  if (ABCJS.synth && ABCJS.synth.supportsAudio() && tunes.length) {
    audio.innerHTML = '';
    controller = new ABCJS.synth.SynthController();
    controller.load(audio, null, { displayPlay: true, displayProgress: true, displayRestart: true });
    controller.setTune(tunes[0], false).catch(() => {});
  }
}
let pending = null;
new ResizeObserver(() => {
  const width = element.querySelector('.score-sheet').clientWidth;
  if (!width || Math.abs(width - lastWidth) < 24) return;
  clearTimeout(pending);
  pending = setTimeout(() => draw(0), 150);
}).observe(element.querySelector('.score-sheet'));
draw(0);
watch('value', () => draw(0));
"""

CSS = """
.score-view { width: 100%; }
.score-empty { color: var(--body-text-color-subdued); padding: 24px; text-align: center; border: 1px dashed var(--border-color-primary); border-radius: 8px; }
.score-sheet { overflow-x: auto; background: #fff; border-radius: 8px; margin-top: 6px; }
/* Gradio's ".prose *" sets the theme text color on every element, which abcjs's currentColor inherits. */
.score-sheet, .score-sheet * { color: #111 !important; }
.score-sheet svg { max-width: 100%; }
.score-audio { margin: 4px 0; }
"""


def ScoreView(**kwargs):
    # A language-neutral placeholder: template props are not run through gr.I18n.
    return gr.HTML(value="", html_template=TEMPLATE, css_template=CSS, js_on_load=JS, head=HEAD,
                   empty="&#9835;", **kwargs)
