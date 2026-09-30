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
let controller = null;
function draw(attempt) {
  const abc = (props.value || '').trim();
  const sheet = element.querySelector('.score-sheet');
  const audio = element.querySelector('.score-audio');
  const empty = element.querySelector('.score-empty');
  if (controller) { try { controller.pause(); } catch (e) {} }
  if (!abc) { sheet.innerHTML = ''; audio.innerHTML = ''; empty.style.display = 'block'; return; }
  empty.style.display = 'none';
  if (!window.ABCJS) { if ((attempt || 0) < 50) setTimeout(() => draw((attempt || 0) + 1), 200); return; }
  const tunes = ABCJS.renderAbc(sheet, abc, { responsive: 'resize', add_classes: true, paddingtop: 4, paddingbottom: 4 });
  if (ABCJS.synth && ABCJS.synth.supportsAudio() && tunes.length) {
    audio.innerHTML = '';
    controller = new ABCJS.synth.SynthController();
    controller.load(audio, null, { displayPlay: true, displayProgress: true, displayRestart: true });
    controller.setTune(tunes[0], false).catch(() => {});
  }
}
draw(0);
watch('value', () => draw(0));
"""

CSS = """
.score-view { width: 100%; }
.score-empty { color: var(--body-text-color-subdued); padding: 24px; text-align: center; border: 1px dashed var(--border-color-primary); border-radius: 8px; }
.score-sheet { overflow-x: auto; background: #fff; border-radius: 8px; margin-top: 6px; }
.score-sheet svg { max-width: 100%; }
.score-audio { margin: 4px 0; }
"""


def ScoreView(**kwargs):
    # A language-neutral placeholder: template props are not run through gr.I18n.
    return gr.HTML(value="", html_template=TEMPLATE, css_template=CSS, js_on_load=JS, head=HEAD,
                   empty="&#9835;", **kwargs)
