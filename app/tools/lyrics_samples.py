"""Generate lyric-completion samples for prompt review.

    python app/tools/lyrics_samples.py OUTPUT_DIR [--no-thinking] [--effort low|high|max] [--only name,...]

Writes one Markdown file per case (inputs, output, melody-fit check, latency) plus
prompt.md with the system prompt, so a reviewer can judge the lyrics as written work.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from studio.core import scores  # noqa: E402
from studio.core.assist import (LyricsAssistant, LyricsRequest, SECTION_TAG, build_messages,  # noqa: E402
                                count_syllables, language_of)

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"

CASES = {
    "ko_ballad_theme": LyricsRequest(
        style="Korean, melancholic ballad, warm male vocal, acoustic piano, strings, bass, 72 BPM",
        title="첫눈", theme="헤어진 사람을 첫눈 오는 날 버스 정류장에서 떠올린다", ui_lang="ko"),
    "en_pop_continue": LyricsRequest(
        style="English, warm pop, expressive female vocal, acoustic piano, bass, drums, 88 BPM", title="Paper Boats",
        lyrics="[Verse]\nFold the morning into paper boats\nLet them drift where the river goes\n"
               "Every wish a little sail of white\nCarried off into the light\n"),
    "en_hiphop_theme": LyricsRequest(
        style="English, dark hip-hop, warm male vocal, 808 bass, synth, drums, 92 BPM",
        theme="working the late shift at a 24-hour diner, saving up to leave town"),
    "ja_anime_theme": LyricsRequest(
        style="Japanese, energetic J-pop rock, expressive female vocal, electric guitar, synth, drums, 150 BPM",
        theme="夏の終わり、自転車で坂道を下りながら友達との約束を思い出す", ui_lang="ko"),
    "ko_kpop_hook": LyricsRequest(
        style="Korean, energetic K-pop EDM, male and female duet, synth, 808 bass, drums, 124 BPM",
        lyrics="[Verse]\n\n[Chorus]\n불 꺼진 도시 위로 달려\n너만 보여 Midnight Run\n", ui_lang="ko"),
    "en_country_title": LyricsRequest(
        style="English, warm country, warm male vocal, acoustic guitar, violin, bass, drums, 96 BPM",
        title="Gravel Road"),
    "en_jazz_scattered": LyricsRequest(
        style="English, romantic jazz, expressive female vocal, acoustic piano, bass, drums, saxophone, 118 BPM",
        theme="Sunday mornings in a small apartment",
        lyrics="[Verse]\nCoffee going cold beside the window\n\n[Chorus]\nStay in, stay in\n"),
    "zh_ballad_theme": LyricsRequest(
        style="Mandarin, gentle ballad, expressive female vocal, acoustic piano, strings, 70 BPM",
        theme="在异乡的夜里给妈妈打电话，却说不出想家"),
    "cover_fit_ko": LyricsRequest(
        style="Korean, warm acoustic folk, expressive female vocal, acoustic guitar, ukulele, bass, 100 BPM",
        theme="이사 가는 날, 빈 방에 남은 것들", ui_lang="ko",
        melody=scores.melody_outline((EXAMPLES / "melody.abc").read_text(encoding="utf-8"))),
}


# A second set with fresh briefs, to check that prompt changes generalize.
CASES_NEW = {
    "ko_ballad_snack": LyricsRequest(
        style="Korean, nostalgic ballad, expressive female vocal, acoustic piano, strings, 70 BPM",
        theme="십 년 만에 다시 가 본 고등학교 앞 분식집", ui_lang="ko"),
    "ko_indie_laundry": LyricsRequest(
        style="Korean, gentle indie acoustic, warm male vocal, acoustic guitar, bass, 92 BPM",
        title="빨래", theme="비 오는 일요일, 자취방에서 마르지 않는 빨래", ui_lang="ko"),
    "en_rock_lastshow": LyricsRequest(
        style="English, epic rock, warm male vocal, electric guitar, bass, drums, 140 BPM",
        theme="our garage band's last show before everyone leaves for college"),
    "en_rnb_hoodie": LyricsRequest(
        style="English, romantic R&B, expressive female vocal, Rhodes, bass, drums, 90 BPM",
        lyrics="[Verse]\nYou left your hoodie on my chair\nIt still smells like the ferry\n"),
    "ja_ballad_lasttrain": LyricsRequest(
        style="Japanese, melancholic ballad, expressive female vocal, acoustic piano, strings, 72 BPM",
        title="終電", ui_lang="ko"),
    "en_edm_festival": LyricsRequest(
        style="English, uplifting EDM, expressive female vocal, synth, 808 bass, drums, 128 BPM",
        theme="running into an ex in the crowd at a summer festival"),
    "zh_citypop_store": LyricsRequest(
        style="Mandarin, nostalgic city pop, warm male vocal, Rhodes, bass, drums, brass, 112 BPM",
        theme="深夜便利店的店员和一个每天同一时间来的常客"),
}


def melody_from(path):
    return scores.melody_outline(Path(path).read_text(encoding="utf-8"))


def fit_report(request, lyrics):
    """Compare each written line with the melody's target syllables."""
    if not request.melody:
        return ""
    language = language_of(request)
    written, current = [], None
    for line in lyrics.splitlines():
        if match := SECTION_TAG.match(line):
            current = {"label": match.group(1).lower(), "lines": []}
            written.append(current)
        elif line.strip() and current is not None:
            current["lines"].append(line.strip())
    rows, hits, total = [], 0, 0
    for index, target in enumerate(request.melody):
        got = written[index] if index < len(written) else {"label": "(missing)", "lines": []}
        rows.append(f"- [{target['label']}] vs [{got['label']}]")
        for position in range(max(len(target["phrases"]), len(got["lines"]))):
            want = target["phrases"][position] if position < len(target["phrases"]) else None
            line = got["lines"][position] if position < len(got["lines"]) else ""
            have = count_syllables(line, language) if line else None
            ok = want is not None and have is not None and abs(want - have) <= 1
            hits += ok
            total += want is not None
            rows.append(f"  - target {want} / written {have} {'ok' if ok else 'MISS'}: {line}")
    return f"\n## Melody fit ({hits}/{total} lines within 1 syllable)\n" + "\n".join(rows) + "\n"


def run_case(assistant, name, request, out):
    started = time.monotonic()
    try:
        lyrics, error = assistant.complete(request), None
    except Exception as exc:  # recorded in the sample file for the reviewer
        lyrics, error = "", f"{type(exc).__name__}: {exc}"
    seconds = time.monotonic() - started
    body = [f"# {name}", "", "## Input",
            f"- Style: {request.style}", f"- Title: {request.title or '-'}", f"- Theme: {request.theme or '-'}",
            f"- Writing language: {language_of(request)}"]
    if request.melody:
        body.append("- Melody: " + "; ".join(f"{s['label']}: {s['phrases'] or 'instrumental'}" for s in request.melody))
    body += ["- Lyrics the person already wrote:", "```", request.lyrics.strip() or "(empty)", "```", "",
             f"## Output ({seconds:.1f}s)", "```", lyrics.strip() if lyrics else f"ERROR {error}", "```"]
    body.append(fit_report(request, lyrics) if lyrics else "")
    (out / f"{name}.md").write_text("\n".join(body), encoding="utf-8")
    if lyrics:
        write_listener_copy(out, name, request.style, lyrics)
    return name, seconds, error


def write_listener_copy(out, name, style, lyrics):
    """Just the song, with the genre a listener would hear — what the reviewer reads."""
    genre = ", ".join(part.strip() for part in style.split(",")[:2])
    (out / "listen").mkdir(exist_ok=True)
    (out / "listen" / f"{name}.txt").write_text(f"({genre})\n\n{lyrics.strip()}\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--no-thinking", action="store_true")
    parser.add_argument("--effort", default=None, help="default: the app's (low)")
    parser.add_argument("--only", default="")
    parser.add_argument("--set", choices=("base", "new"), default="base", help="which briefs to run")
    parser.add_argument("--melody", action="append", default=[], help="name=path.abc: add a cover-fit case from a score")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    fresh = args.set == "new"
    cases = dict(CASES_NEW if fresh else CASES)
    for item in args.melody:
        name, path = item.split("=", 1)
        if "_en" in name:
            theme = "first snow in a city where I know nobody" if fresh else "the last night before a friend moves abroad"
            cases[name] = LyricsRequest(style="English, warm pop, expressive female vocal, acoustic piano, bass, drums",
                                        theme=theme, melody=melody_from(path))
        else:
            theme = "졸업식이 끝난 오후, 텅 빈 교실" if fresh else CASES["cover_fit_ko"].theme
            cases[name] = LyricsRequest(style=CASES["cover_fit_ko"].style, theme=theme, ui_lang="ko",
                                        melody=melody_from(path))
    if args.only:
        cases = {k: v for k, v in cases.items() if k in args.only.split(",")}
    assistant = LyricsAssistant(thinking=not args.no_thinking, effort=args.effort)
    example = build_messages(next(iter(cases.values())))
    (args.output / "prompt.md").write_text(
        f"# Prompt\n\nthinking={assistant.thinking} effort={assistant.effort} model={assistant.model}\n\n"
        f"## System\n```\n{example[0]['content']}\n```\n\n## Example user message\n```\n{example[1]['content']}\n```\n",
        encoding="utf-8")
    with ThreadPoolExecutor(max_workers=6) as pool:
        for name, seconds, error in pool.map(lambda item: run_case(assistant, item[0], item[1], args.output),
                                             cases.items()):
            print(f"{name}: {seconds:.1f}s {'ERROR ' + error if error else ''}")


if __name__ == "__main__":
    main()
