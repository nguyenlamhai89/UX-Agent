import os
import sys
import json
import asyncio
import re
import html
import hashlib
import tempfile
import unicodedata
from pathlib import Path
import webbrowser
import shutil
from urllib.parse import urlparse


DEFAULT_MAX_INPUT_BYTES = 50 * 1024 * 1024
INPUT_WARNING_RATIO = 0.8
LARGE_STUDY_INTERVIEWEE_COUNT = 20
MANIFEST_SCHEMA_VERSION = 1
RENDERER_VERSION = "2.0.0"
MEDIA_EXTENSIONS = {".mp3", ".wav", ".m4a", ".qta", ".mp4", ".mkv", ".ogg", ".flac"}


class SkillError(Exception):
    """Structured terminal failure returned to the orchestrator."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message

async def get_audio_duration(f):
    try:
        proc = await asyncio.create_subprocess_exec(
            'ffprobe', '-v', 'error', '-show_entries',
            'format=duration', '-of',
            'default=noprint_wrappers=1:nokey=1', f,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        return float(stdout.decode().strip())
    except Exception:
        return 0.0

async def get_media_stats(media_paths):
    """Return duration stats for explicitly declared media inputs."""
    unique_files = sorted({str(path) for path in media_paths})
    total_duration_sec = 0.0
    if unique_files:
        if shutil.which('ffprobe') is None:
            print("Warning: 'ffprobe' is not installed or not in PATH. Audio duration cannot be calculated.", file=sys.stderr)
        else:
            tasks = [get_audio_duration(f) for f in unique_files]
            durations = await asyncio.gather(*tasks)
            total_duration_sec = sum(durations)
            
    mins = int(total_duration_sec // 60)
    secs = int(total_duration_sec % 60)
    total_time_html = f"{mins} <span class='text-sm font-normal text-slate-400 mx-1'>mins</span> {secs} <span class='text-sm font-normal text-slate-400 ml-1'>secs</span>"

    return {
        "total_time_html": total_time_html,
        "media_count": len(unique_files),
    }


async def get_folder_stats(media_paths):
    """Backward-compatible alias; inputs must now be explicit media paths."""
    return await get_media_stats(media_paths)


def _safe_link(url):
    parsed = urlparse(html.unescape(url).strip())
    return parsed.scheme.casefold() in {"http", "https", "mailto"}


def render_inline_markdown(text):
    if not text or text == "N/A":
        return ""
    rendered = html.escape(str(text), quote=False)
    rendered = re.sub(
        r'&lt;mark\s+style="background-color:\s*yellow;?"&gt;(.*?)&lt;/mark&gt;',
        r'<mark class="bg-yellow-200 text-slate-900 rounded px-0.5">\1</mark>',
        rendered,
        flags=re.IGNORECASE,
    )
    rendered = re.sub(r"&lt;br\s*/?&gt;", "<br>", rendered, flags=re.IGNORECASE)
    rendered = re.sub(
        r'\[(.*?)\]\((.*?)\)',
        lambda match: (
            f'<a href="{html.escape(html.unescape(match.group(2)), quote=True)}" '
            'class="text-blue-600 hover:underline hover:text-blue-800" '
            f'target="_blank" rel="noopener noreferrer">{match.group(1)}</a>'
            if _safe_link(match.group(2))
            else match.group(1)
        ),
        rendered,
    )
    # Bold
    rendered = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', rendered)
    # Italic
    rendered = re.sub(r'(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)', r'<em>\1</em>', rendered)
    return rendered


def json_for_html(value):
    """Serialize JSON safely for embedding in an HTML script element."""
    return (
        json.dumps(value, ensure_ascii=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )


def extract_transcript_headers(md_text, audio_names=None):
    """Return interviewee names from the canonical mapped-transcript table."""
    headers = []
    for line in md_text.split('\n'):
        stripped = line.strip()
        if not stripped.startswith('|') or '---' in stripped:
            continue
        lowered = stripped.lower()
        if ('theme' in lowered or 'topic' in lowered) and 'question' in lowered:
            cols = [c.strip() for c in stripped.strip('|').split('|')]
            headers = cols[4:] if len(cols) > 4 else []
            break

    if audio_names:
        headers = list(headers)
        for index, name in enumerate(audio_names):
            if index < len(headers):
                headers[index] = name
            else:
                headers.append(name)

    return headers


def normalize_interviewee_name(value):
    """Normalize display names and transcript filename suffixes for matching."""
    normalized = unicodedata.normalize('NFKD', value or '')
    normalized = ''.join(char for char in normalized if not unicodedata.combining(char))
    return ''.join(char for char in normalized.casefold() if char.isalnum())


def match_full_transcript_inputs(full_transcript_paths, interviewee_names):
    """Validate and match explicit transcript-*.md inputs to interviewees."""
    if not isinstance(full_transcript_paths, list) or not full_transcript_paths:
        raise ValueError("full_transcript_paths must be a non-empty list of transcript-*.md files")

    candidates = {}
    for raw_path in full_transcript_paths:
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError("Every full_transcript_paths item must be a non-empty string")

        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            raise ValueError(f"Full transcript path must be absolute: {raw_path}")
        if not candidate.is_file():
            raise ValueError(f"Full transcript file does not exist: {raw_path}")

        filename_match = re.match(r'^transcript[-_](.+)\.md$', candidate.name, flags=re.IGNORECASE)
        if not filename_match:
            raise ValueError(f"Full transcript filename must match transcript-*.md: {candidate.name}")

        normalized_suffix = normalize_interviewee_name(filename_match.group(1))
        if not normalized_suffix:
            raise ValueError(f"Full transcript filename has no interviewee name: {candidate.name}")
        if normalized_suffix in candidates:
            raise ValueError(
                f"Multiple full transcripts resolve to the same interviewee: "
                f"{candidates[normalized_suffix].name}, {candidate.name}"
            )
        candidates[normalized_suffix] = candidate

    matched = {}
    missing = []
    for interviewee in interviewee_names:
        normalized_name = normalize_interviewee_name(interviewee)
        transcript_file = candidates.pop(normalized_name, None)
        if transcript_file is None:
            missing.append(interviewee)
        else:
            matched[interviewee] = transcript_file

    if missing:
        raise ValueError("Missing full transcript input for: " + ", ".join(missing))
    if candidates:
        unmatched_files = ", ".join(path.name for path in candidates.values())
        raise ValueError("Full transcript inputs do not match mapped interviewees: " + unmatched_files)

    return matched


def render_full_transcript_markdown(md_text):
    """Render timestamped transcript Markdown into safe, readable HTML."""
    blocks = []
    list_items = []

    def flush_list():
        nonlocal list_items
        if list_items:
            blocks.append(
                '<ul class="list-disc pl-5 space-y-2 text-sm text-slate-700 leading-7">'
                + ''.join(list_items)
                + '</ul>'
            )
            list_items = []

    def render_safe_inline(value):
        rendered = html.escape(value, quote=False)
        rendered = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', rendered)
        rendered = re.sub(r'(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)', r'<em>\1</em>', rendered)
        rendered = rendered.replace('&lt;br&gt;', '<br>').replace('&lt;br/&gt;', '<br>')
        return rendered

    for raw_line in md_text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            flush_list()
            continue

        heading_match = re.match(r'^(#{1,4})\s+(.+)$', stripped)
        if heading_match:
            flush_list()
            level = min(len(heading_match.group(1)) + 1, 5)
            blocks.append(
                f'<h{level} class="font-semibold text-slate-900 mt-6 mb-3">'
                f'{render_safe_inline(heading_match.group(2))}</h{level}>'
            )
            continue

        if re.match(r'^[-*_]{3,}$', stripped):
            flush_list()
            blocks.append('<hr class="border-slate-200 my-5">')
            continue

        if stripped.startswith(('- ', '* ')):
            list_items.append(f'<li>{render_safe_inline(stripped[2:])}</li>')
            continue

        flush_list()
        is_speaker_line = bool(re.match(r'^\*\*\[[0-9]{1,2}:[0-9]{2}', stripped))
        paragraph_class = (
            'text-sm font-semibold text-blue-700 mt-5 mb-1'
            if is_speaker_line
            else 'text-sm text-slate-700 leading-7 mb-3'
        )
        blocks.append(f'<p class="{paragraph_class}">{render_safe_inline(stripped)}</p>')

    flush_list()
    return '\n'.join(blocks)


def build_full_transcript_ui(interviewee_names, transcript_files):
    """Build the table footer and embedded right-side transcript drawer."""
    footer_cells = [
        '<td colspan="4" class="px-4 py-4 text-sm font-semibold text-slate-700 bg-slate-50">'
        'Bản ghi phỏng vấn đầy đủ</td>'
    ]
    panels = []

    for index, interviewee in enumerate(interviewee_names):
        panel_id = f'full-transcript-{index}'
        escaped_name = html.escape(interviewee)
        transcript_file = transcript_files[interviewee]
        button_title = f'Xem toàn bộ bản ghi của {escaped_name}'
        button_classes = (
            'inline-flex items-center justify-center rounded-lg border border-blue-200 bg-blue-50 '
            'px-3 py-2 text-sm font-semibold text-blue-700 hover:bg-blue-100 focus:outline-none '
            'focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 transition-colors'
        )
        footer_cells.append(
            f'<td class="px-4 py-4 text-center bg-slate-50">'
            f'<button type="button" class="{button_classes}" '
            f'onclick="openTranscriptDrawer(\'{panel_id}\', this)" '
            f'aria-controls="full-transcript-drawer" title="{button_title}">'
            'Xem tất cả</button></td>'
        )

        transcript_md = transcript_file.read_text(encoding='utf-8')
        transcript_html = render_full_transcript_markdown(transcript_md)
        transcript_payload = json_for_html({"html": transcript_html})
        source_label = html.escape(transcript_file.name)

        panels.append(
            f'<article id="{panel_id}" data-full-transcript-panel class="hidden">'
            f'<p class="text-xs font-medium uppercase tracking-wide text-slate-400 mb-1">{source_label}</p>'
            f'<h2 class="text-xl font-semibold text-slate-900 mb-4">Bản ghi đầy đủ — {escaped_name}</h2>'
            f'<div class="mb-5">'
            f'<div class="relative w-full">'
            f'<div class="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">'
            f'<svg class="h-5 w-5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg>'
            f'</div>'
            f'<input type="text" id="full-transcript-search-{index}" '
            f'oninput="searchFullTranscript(this, \'{panel_id}\')" '
            f'placeholder="Search in full transcript..." '
            f'aria-label="Tìm kiếm trong bản ghi đầy đủ của {escaped_name}" '
            f'class="block w-full pl-10 pr-10 py-2 border border-slate-300 rounded-lg leading-5 bg-white placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-blue-500 sm:text-sm transition duration-150 ease-in-out">'
            f'<button id="full-transcript-clear-{index}" type="button" '
            f'onclick="clearFullTranscriptSearch(\'full-transcript-search-{index}\', \'{panel_id}\')" '
            f'class="hidden absolute inset-y-0 right-0 pr-3 flex items-center text-slate-400 hover:text-slate-600 focus:outline-none" '
            f'aria-label="Xóa tìm kiếm">'
            f'<svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>'
            f'</button>'
            f'</div>'
            f'</div>'
            f'<script type="application/json" data-full-transcript-payload>{transcript_payload}</script>'
            f'<div class="transcript-document" data-full-transcript-document '
            f'aria-live="polite"></div>'
            '</article>'
        )

    footer_html = '<tr>' + ''.join(footer_cells) + '</tr>'
    drawer_html = f'''
<div id="full-transcript-drawer-root" class="fixed inset-0 z-50 hidden" aria-hidden="true">
    <button type="button" class="absolute inset-0 w-full h-full bg-slate-950/35 backdrop-blur-[1px] cursor-default" aria-label="Đóng bản ghi đầy đủ" onclick="closeTranscriptDrawer()"></button>
    <aside id="full-transcript-drawer" role="dialog" aria-modal="true" aria-labelledby="full-transcript-drawer-title" class="absolute inset-y-0 right-0 w-full max-w-2xl bg-white shadow-2xl translate-x-full transition-transform duration-300 ease-out flex flex-col">
        <div class="flex items-center justify-between gap-4 border-b border-slate-200 px-5 py-4 sm:px-7">
            <h2 id="full-transcript-drawer-title" class="text-base font-semibold text-slate-900">Bản ghi phỏng vấn đầy đủ</h2>
            <button id="full-transcript-drawer-close" type="button" onclick="closeTranscriptDrawer()" class="inline-flex h-9 w-9 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500" aria-label="Đóng">
                <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
            </button>
        </div>
        <div class="flex-1 overflow-y-auto px-5 py-5 sm:px-7">
            {''.join(panels)}
        </div>
    </aside>
</div>
'''
    return footer_html, drawer_html

def parse_transcript_to_html(md_text, audio_names=None):
    rows = []
    lines = md_text.split('\n')
    header_found = False
    headers = extract_transcript_headers(md_text, audio_names)
    for line in lines:
        if line.strip().startswith('|'):
            if '---' in line:
                continue
            if not header_found and ('theme' in line.lower() or 'topic' in line.lower()) and 'question' in line.lower():
                header_found = True
                continue
            if not header_found:
                continue
            line_str = line.strip()
            if line_str.startswith('|'): line_str = line_str[1:]
            if line_str.endswith('|'): line_str = line_str[:-1]
            cols = [c.strip() for c in line_str.split('|')]
            if len(cols) > 0 and cols[0].isdigit():
                num = cols[0]
                while len(cols) < 5:
                    cols.append("")
                theme = render_inline_markdown(cols[1])
                question = render_inline_markdown(cols[2])
                obs = render_inline_markdown(cols[3])
                
                tds = ""
                for i in range(len(headers)):
                    col_idx = i + 4
                    ans = cols[col_idx] if col_idx < len(cols) else ""
                    ans = render_inline_markdown(ans)
                    tds += f'<td class="px-4 py-4 text-sm text-slate-700 leading-relaxed align-top">{ans}</td>\n'
                
                rows.append(f"""
                <tr class="hover:bg-slate-100">
                    <td class="px-2 py-4 whitespace-nowrap text-sm text-slate-500 font-medium align-top text-center w-1">{num}</td>
                    <td class="px-4 py-4 text-sm text-slate-800 leading-relaxed align-top">{theme}</td>
                    <td class="px-4 py-4 text-sm text-slate-800 leading-relaxed align-top">{question}</td>
                    <td class="px-4 py-4 text-sm text-slate-800 leading-relaxed align-top">{obs}</td>
                    {tds}
                </tr>
                """)
                
    transcript_thead = f"""
                                        <th scope="col" class="px-2 py-3 text-center text-xs font-medium text-slate-500 uppercase tracking-wider w-1 whitespace-nowrap">#</th>
                                        <th scope="col" class="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider w-48">Theme</th>
                                        <th scope="col" class="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider w-64">Question</th>
                                        <th scope="col" class="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider w-48">Observed Variable</th>
"""
    for user in headers:
        escaped_user = html.escape(user)
        initial = html.escape(user[0].upper()) if user else "U"
        transcript_thead += f"""
                                        <th scope="col" class="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider min-w-[300px]">
                                            <div class="flex items-center">
                                                <div class="w-6 h-6 rounded-full bg-slate-200 text-slate-600 flex items-center justify-center font-bold text-xs mr-2">{initial}</div>
                                                {escaped_user}
                                            </div>
                                        </th>
"""
    return "\n".join(rows), transcript_thead

def parse_interviewee_quotes(md_text):
    """Parse per-interviewee insight sections to build a quotes lookup.

    Parses sections like '# Insights — Chị Dung' with tables
    containing '# | Insight | Quotes' columns.

    Returns:
        dict: {insight_text: {user_name: quote_text}}
    """
    quotes = {}
    lines = md_text.split('\n')
    current_user = None
    header_found = False

    for line in lines:
        stripped = line.strip()

        # Detect interviewee section headers like "# Insights — Chị Dung"
        if stripped.startswith('# Insights') and '—' in stripped:
            parts = stripped.split('—', 1)
            if len(parts) > 1:
                current_user = parts[1].strip()
            header_found = False
            continue

        # Stop at Data Saturation Matrix section
        if stripped.startswith('# Data Saturation Matrix'):
            break

        if current_user is None:
            continue

        if stripped.startswith('|'):
            if '---' in stripped:
                continue
            if ('Insight' in stripped or 'Quotes' in stripped) and not header_found:
                header_found = True
                continue
            if not header_found:
                continue

            line_str = stripped
            if line_str.startswith('|'):
                line_str = line_str[1:]
            if line_str.endswith('|'):
                line_str = line_str[:-1]
            cols = [c.strip() for c in line_str.split('|')]

            if len(cols) > 0 and cols[0].isdigit():
                insight = cols[1] if len(cols) > 1 else ""
                quote = cols[2] if len(cols) > 2 else ""
                if insight:
                    if insight not in quotes:
                        quotes[insight] = {}
                    quotes[insight][current_user] = quote

    return quotes


def parse_insights_to_html(md_text, audio_names=None):
    """Parse the Data Saturation Matrix section and render HTML rows.

    Targets ONLY the '# Data Saturation Matrix' section (columns:
    Insight | User1 | User2 | ...) and links saturation markers
    (🔵/🌐/⚪️) to quotes from per-interviewee sections.
    """
    # Build the quotes lookup from per-interviewee sections
    quotes_lookup = parse_interviewee_quotes(md_text)

    rows = []
    lines = md_text.split('\n')
    header_found = False
    headers = []
    in_saturation = False
    unique_id = 1
    row_num = 0

    for line in lines:
        stripped = line.strip()

        # Enter saturation matrix section
        if stripped.startswith('# Data Saturation Matrix'):
            in_saturation = True
            continue

        # Exit at known section boundaries
        if in_saturation and (stripped.startswith('## Data Saturation Chart') or
                              stripped.startswith('## Summary') or
                              stripped.startswith('## New Insights') or
                              stripped.startswith('## Saturation Data')):
            break

        if not in_saturation:
            continue

        if stripped.startswith('|'):
            if '---' in stripped:
                continue

            # Parse header row
            if 'Insight' in stripped and not header_found:
                header_found = True
                cols = [c.strip() for c in stripped.strip('|').split('|')]
                # First col is 'Insight', rest are user names
                headers = cols[1:] if len(cols) > 1 else []
                continue

            if not header_found:
                continue

            # Parse data row
            line_str = stripped
            if line_str.startswith('|'):
                line_str = line_str[1:]
            if line_str.endswith('|'):
                line_str = line_str[:-1]
            cols = [c.strip() for c in line_str.split('|')]

            # Skip summary rows like "**🔵 New Insights** | 10"
            if len(cols) > 0 and '**' in cols[0]:
                continue

            if len(cols) > 0 and cols[0]:
                insight = cols[0]
                row_num += 1

                tds = ""
                for i in range(len(headers)):
                    col_idx = i + 1
                    marker = cols[col_idx] if col_idx < len(cols) else ""
                    escaped_marker = html.escape(marker)

                    user_name = headers[i] if i < len(headers) else ""
                    # Look up the quote from the per-interviewee section
                    quote_text = quotes_lookup.get(insight, {}).get(user_name, "")

                    if marker and marker not in ("N/A", "", "-"):
                        if quote_text:
                            tds += f"""
                        <td class="p-0 align-top">
                            <button onclick="toggleQuote('insight-{unique_id}')" class="w-full h-full min-h-[60px] flex flex-col items-center justify-start p-3 transition-all focus:outline-none focus:ring-2 focus:ring-blue-500/50">
                                <div id="icon-insight-{unique_id}" class="text-blue-500 text-xl transition-all duration-300">{escaped_marker}</div>
                                <div id="quote-insight-{unique_id}" class="hidden w-full mt-2 text-left text-[14px] text-slate-700 italic bg-blue-50 p-3 rounded-md border-l-2 border-blue-400 shadow-sm relative before:absolute before:-top-2 before:left-1/2 before:-translate-x-1/2 before:border-4 before:border-transparent before:border-b-blue-400">
                                    {render_inline_markdown(quote_text)}
                                </div>
                            </button>
                        </td>"""
                        else:
                            # Marker exists but no quote found
                            tds += f"""
                        <td class="px-4 py-4 align-top text-center">
                            <span class="text-xl">{escaped_marker}</span>
                        </td>"""
                        unique_id += 1
                    else:
                        tds += f"""
                        <td class="px-4 py-4 align-top border-l border-dashed border-slate-200 bg-slate-50/30 group-hover:bg-transparent text-center"><span class="text-slate-300 text-xl">-</span></td>"""

                rows.append(f"""
                <tr class="hover:bg-slate-100 transition-colors group">
                    <td class="px-2 py-4 whitespace-nowrap text-sm text-slate-500 font-medium align-top text-center w-1">{row_num}</td>
                    <td class="px-4 py-4 text-sm text-slate-800 font-medium leading-relaxed align-top">{render_inline_markdown(insight)}</td>
                    {tds}
                </tr>
                """)

    # Override headers with audio names if available
    if audio_names:
        for i, name in enumerate(audio_names):
            if i < len(headers):
                headers[i] = name
            else:
                headers.append(name)

    saturation_thead = f"""
                                        <th scope="col" class="px-2 py-3 text-center text-xs font-medium text-slate-500 uppercase tracking-wider w-1 whitespace-nowrap">#</th>
                                        <th scope="col" class="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider w-full min-w-[300px]">Insight</th>
"""
    for user in headers:
        escaped_user = html.escape(user)
        initial = html.escape(user[0].upper()) if user else "U"
        saturation_thead += f"""
                                        <th scope="col" class="px-4 py-3 text-center text-xs font-medium text-slate-500 uppercase tracking-wider min-w-[200px]">
                                            <div class="flex flex-col items-center">
                                                <div class="w-8 h-8 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center font-bold mb-1 shadow-sm">{initial}</div>
                                                {escaped_user}
                                            </div>
                                        </th>
"""
    return "\n".join(rows), saturation_thead, headers

def extract_chart_data(insights_md, audio_names=None):
    lines = insights_md.split('\n')
    new_insight_counts = []
    saturation_headers = []
    in_saturation = False
    header_found = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith('# Data Saturation Matrix'):
            in_saturation = True
            continue

        # Extract saturation matrix headers for fallback labels
        if in_saturation and not header_found and stripped.startswith('|') and 'Insight' in stripped:
            cols = [c.strip() for c in stripped.strip('|').split('|')]
            saturation_headers = cols[1:] if len(cols) > 1 else []
            header_found = True
            continue

        if '|' in line and '**🔵 New Insights**' in line:
            cols = [c.strip() for c in line.strip().strip('|').split('|')]
            for val in cols[1:]:
                try:
                    new_insight_counts.append(int(val))
                except ValueError:
                    pass
            break

    data = []
    cumulative_total = 0
    for count in new_insight_counts:
        cumulative_total += count
        data.append(cumulative_total)

    labels = []
    if audio_names:
        labels = list(audio_names[:len(data)]) if data else ["User 1"]
        while len(labels) < len(data):
            labels.append(f"User {len(labels)+1}")
    elif saturation_headers:
        labels = list(saturation_headers[:len(data)]) if data else saturation_headers[:1] or ["User 1"]
        while len(labels) < len(data):
            labels.append(f"User {len(labels)+1}")
    else:
        labels = [f"User {i+1}" for i in range(len(data))] if data else ["User 1"]

    if not data:
        data = [0]
    return json_for_html(labels), json_for_html(data), data[-1] if data else 0

def extract_summary_insights(insights_md):
    lines = insights_md.split('\n')
    bullets = []
    capture = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('## Summary of Discovered Insights') or stripped.startswith('## Summary of Master Insights'):
            capture = True
            continue
        if capture and (stripped.startswith('#') or stripped.startswith('---')) and not stripped.startswith('## Summary'):
            capture = False
            continue
        if capture:
            if stripped.startswith('- '):
                html_line = stripped[2:]
                html_line = render_inline_markdown(html_line)
                bullets.append(f"<li>{html_line}</li>")
            elif stripped.startswith('|'):
                if '---' in stripped or 'Insight' in stripped:
                    continue
                cols = [c.strip() for c in stripped.strip('|').split('|')]
                if len(cols) >= 2:
                    if cols[0].isdigit():
                        insight_text = cols[1]
                    else:
                        insight_text = cols[0]
                    insight_text = render_inline_markdown(insight_text)
                    bullets.append(f"<li>{insight_text}</li>")
    return "\n".join(bullets)

def parse_journey_map(md_text):
    if not md_text:
        return ""
        
    lines = md_text.split('\n')
    header_found = False
    rows = []
    
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('|'):
            if '---' in stripped:
                continue
            if 'Dimension' in stripped and not header_found:
                header_found = True
                continue
            if not header_found:
                continue
                
            line_str = stripped
            if line_str.startswith('|'): line_str = line_str[1:]
            if line_str.endswith('|'): line_str = line_str[:-1]
            cols = [c.strip() for c in line_str.split('|')]
            
            if len(cols) > 0:
                dimension = cols[0]
                dimension = render_inline_markdown(dimension.replace('**', '').strip())
                if not dimension:
                    continue
                    
                is_emotion = "emotion" in dimension.lower()
                tds = ""
                for i in range(1, 6):
                    val = cols[i] if i < len(cols) else ""
                    val = render_inline_markdown(val)
                    if is_emotion and val:
                        match = re.search(r'([1-5])', val)
                        if match:
                            rating = int(match.group(1))
                            emotion_text = re.sub(r'^[1-5]\s*[-:]\s*', '', val)
                            
                            if rating == 5:
                                badge_class = "bg-white border-emerald-500 text-emerald-700 shadow-[0_0_8px_rgba(16,185,129,0.15)] animate-pulse"
                            elif rating == 4:
                                badge_class = "bg-white border-blue-500 text-blue-700 shadow-[0_0_8px_rgba(59,130,246,0.15)]"
                            elif rating == 3:
                                badge_class = "bg-white border-slate-300 text-slate-700 shadow-[0_0_8px_rgba(148,163,184,0.15)]"
                            elif rating == 2:
                                badge_class = "bg-white border-amber-500 text-amber-700 shadow-[0_0_8px_rgba(245,158,11,0.15)]"
                            else: # rating == 1
                                badge_class = "bg-white border-rose-500 text-rose-700 shadow-[0_0_8px_rgba(239,68,68,0.15)]"
                                
                            top_percent = 90 - (rating - 1) * 20
                            
                            val_html = f"""
                            <div class="relative w-full h-24 flex flex-col justify-between items-center py-2 select-none">
                                <!-- 5 parallel lines -->
                                <div class="absolute inset-x-0 top-[10%] h-[1px] bg-slate-200"></div>
                                <div class="absolute inset-x-0 top-[30%] h-[1px] bg-slate-200"></div>
                                <div class="absolute inset-x-0 top-[50%] h-[1px] bg-slate-200"></div>
                                <div class="absolute inset-x-0 top-[70%] h-[1px] bg-slate-200"></div>
                                <div class="absolute inset-x-0 top-[90%] h-[1px] bg-slate-200"></div>
                                
                                <!-- Labels on the left and right -->
                                <span class="absolute left-2 text-[8px] font-semibold text-slate-400 -translate-y-1/2" style="top: 10%;">5</span>
                                <span class="absolute left-2 text-[8px] font-semibold text-slate-400 -translate-y-1/2" style="top: 50%;">3</span>
                                <span class="absolute left-2 text-[8px] font-semibold text-slate-400 -translate-y-1/2" style="top: 90%;">1</span>
                                
                                <span class="absolute right-2 text-[8px] font-semibold text-slate-400 -translate-y-1/2" style="top: 10%;">5</span>
                                <span class="absolute right-2 text-[8px] font-semibold text-slate-400 -translate-y-1/2" style="top: 50%;">3</span>
                                <span class="absolute right-2 text-[8px] font-semibold text-slate-400 -translate-y-1/2" style="top: 90%;">1</span>
                                
                                <!-- Badge -->
                                <div class="absolute left-1/2 -translate-x-1/2 -translate-y-1/2 z-10" style="top: {top_percent}%;">
                                    <span class="px-2.5 py-1 text-xs font-semibold rounded-full shadow-sm border {badge_class} whitespace-nowrap">
                                        {emotion_text}
                                    </span>
                                </div>
                            </div>
                            """
                            tds += f'<td class="px-2 py-2 text-sm text-slate-700 leading-relaxed align-middle border-l border-slate-200">{val_html}</td>\n'
                        else:
                            tds += f'<td class="px-6 py-4 text-sm text-slate-700 leading-relaxed align-top border-l border-slate-200">{val}</td>\n'
                    else:
                        tds += f'<td class="px-6 py-4 text-sm text-slate-700 leading-relaxed align-top border-l border-slate-200">{val}</td>\n'
                
                rows.append(f"""
                <tr class="hover:bg-blue-50/50 transition-colors border-b border-slate-100 last:border-0">
                    <td class="px-6 py-5 whitespace-nowrap text-sm font-semibold text-slate-800 align-top w-48 bg-slate-50">{dimension}</td>
                    {tds}
                </tr>
                """)
                
    return "\n".join(rows)

def _read_payload():
    input_text = ""
    if len(sys.argv) > 1:
        argument = sys.argv[1]
        payload_path = Path(argument).expanduser()
        if argument.endswith(".json") and payload_path.is_file():
            try:
                input_text = payload_path.read_text(encoding="utf-8")
            except OSError as error:
                raise SkillError("INPUT_READ_ERROR", f"Failed to read input JSON file: {error}") from error
        else:
            input_text = argument
    elif not sys.stdin.isatty():
        input_text = sys.stdin.read()

    if not input_text:
        raise SkillError("INVALID_INPUT", "Missing input JSON from arguments, file, or stdin")
    try:
        payload = json.loads(input_text)
    except json.JSONDecodeError as error:
        raise SkillError("INVALID_JSON", f"Invalid input JSON: {error.msg}") from error
    if not isinstance(payload, dict):
        raise SkillError("INVALID_INPUT", "Input JSON must be an object")
    return payload


def _require_string(payload, key):
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SkillError("INVALID_INPUT", f"{key} must be a non-empty string")
    return value.strip()


def _resolve_input_file(value, label):
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise SkillError("INVALID_INPUT", f"{label} must be an absolute path: {value}")
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise SkillError("INPUT_READ_ERROR", f"{label} is not readable: {value}") from error
    if not resolved.is_file():
        raise SkillError("INPUT_READ_ERROR", f"{label} is not a file: {value}")
    return resolved


def _validate_payload(payload):
    insights_path = _resolve_input_file(_require_string(payload, "insights_path"), "insights_path")
    transcript_path = _resolve_input_file(_require_string(payload, "transcript_path"), "transcript_path")
    output_value = _require_string(payload, "output_dir")
    output_dir = Path(output_value).expanduser()
    if not output_dir.is_absolute():
        raise SkillError("INVALID_INPUT", f"output_dir must be an absolute path: {output_value}")
    output_dir = output_dir.resolve(strict=False)

    project_name = _require_string(payload, "project_name")
    if (
        project_name in {".", ".."}
        or Path(project_name).name != project_name
        or "/" in project_name
        or "\\" in project_name
        or any(ord(character) < 32 for character in project_name)
        or len(project_name) > 120
    ):
        raise SkillError("OUTPUT_PATH_INVALID", "project_name must be a safe filename stem of 1-120 characters")

    full_transcript_values = payload.get("full_transcript_paths")
    if not isinstance(full_transcript_values, list) or not full_transcript_values:
        raise SkillError("INVALID_INPUT", "full_transcript_paths must be a non-empty list")
    full_transcript_paths = []
    for value in full_transcript_values:
        if not isinstance(value, str) or not value.strip():
            raise SkillError(
                "INVALID_INPUT",
                "Every full_transcript_paths item must be a non-empty string",
            )
        full_transcript_paths.append(
            _resolve_input_file(value, "full_transcript_paths item")
        )

    journey_value = payload.get("journey_path")
    journey_path = None
    if journey_value is not None:
        if not isinstance(journey_value, str) or not journey_value.strip():
            raise SkillError("INVALID_INPUT", "journey_path must be a non-empty absolute path when provided")
        journey_path = _resolve_input_file(journey_value, "journey_path")

    media_values = payload.get("media_paths", [])
    if not isinstance(media_values, list):
        raise SkillError("INVALID_INPUT", "media_paths must be a list")
    media_paths = []
    for value in media_values:
        if not isinstance(value, str) or not value.strip():
            raise SkillError("INVALID_INPUT", "Every media_paths item must be a non-empty string")
        media_path = _resolve_input_file(value, "media_paths item")
        if media_path.suffix.casefold() not in MEDIA_EXTENSIONS:
            raise SkillError("INVALID_INPUT", f"Unsupported media file extension: {media_path.name}")
        media_paths.append(media_path)

    max_input_bytes = payload.get("max_input_bytes", DEFAULT_MAX_INPUT_BYTES)
    if isinstance(max_input_bytes, bool) or not isinstance(max_input_bytes, int) or max_input_bytes <= 0:
        raise SkillError("INVALID_INPUT", "max_input_bytes must be a positive integer")
    open_browser = payload.get("open_browser", False)
    force = payload.get("force", False)
    if not isinstance(open_browser, bool) or not isinstance(force, bool):
        raise SkillError("INVALID_INPUT", "open_browser and force must be booleans")

    output_file = (output_dir / f"{project_name}.html").resolve(strict=False)
    manifest_file = (output_dir / f"{project_name}.visualize-manifest.json").resolve(strict=False)
    if output_file.parent != output_dir or manifest_file.parent != output_dir:
        raise SkillError("OUTPUT_PATH_INVALID", "Output files must remain inside output_dir")

    return {
        "insights_path": insights_path,
        "transcript_path": transcript_path,
        "full_transcript_paths": full_transcript_paths,
        "journey_path": journey_path,
        "media_paths": media_paths,
        "output_dir": output_dir,
        "output_file": output_file,
        "manifest_file": manifest_file,
        "project_name": project_name,
        "max_input_bytes": max_input_bytes,
        "open_browser": open_browser,
        "force": force,
    }


def _read_text(path, code="INPUT_READ_ERROR"):
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise SkillError(code, f"Failed to read {path}: {error}") from error


def _sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def _file_fingerprint(path, hash_content=True):
    stat = path.stat()
    fingerprint = {
        "path": str(path),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }
    if hash_content:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        fingerprint["sha256"] = digest.hexdigest()
    return fingerprint


def _load_templates():
    template_dir = Path(__file__).parent.parent / "template"
    paths = {
        "base": template_dir / "insights-template.html",
        "overview": template_dir / "modules" / "overview.html",
        "saturation": template_dir / "modules" / "saturation.html",
        "transcript": template_dir / "modules" / "transcript.html",
        "journey": template_dir / "modules" / "journey-map.html",
    }
    templates = {name: _read_text(path, "TEMPLATE_ERROR") for name, path in paths.items()}
    required_placeholders = {
        "base": {"overview_module", "insights_saturation_module", "transcript_module", "journey_module", "project_name"},
        "overview": {"total_interviewees", "total_time_html", "total_insights"},
        "saturation": {"saturation_thead", "insights_rows", "chart_labels", "chart_data", "summary_insights_html"},
        "transcript": {"transcript_thead", "transcript_rows", "transcript_footer", "transcript_drawer"},
        "journey": {"journey_rows"},
    }
    for name, placeholders in required_placeholders.items():
        missing = [key for key in placeholders if "{{ " + key + " }}" not in templates[name]]
        if missing:
            raise SkillError("TEMPLATE_ERROR", f"Template {paths[name].name} is missing placeholders: {', '.join(missing)}")
    return templates, paths


def _build_signature(config, input_paths, template_paths):
    signature_data = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "renderer_version": RENDERER_VERSION,
        "project_name": config["project_name"],
        "inputs": [_file_fingerprint(path) for path in input_paths],
        "templates": [_file_fingerprint(path) for path in template_paths.values()],
        "media": [_file_fingerprint(path, hash_content=False) for path in config["media_paths"]],
    }
    encoded = json.dumps(signature_data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(encoded), signature_data


def _current_output_is_valid(output_file, manifest_file, input_signature):
    if not output_file.is_file() or not manifest_file.is_file():
        return False
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        output_hash = _file_fingerprint(output_file)["sha256"]
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return (
        manifest.get("schema_version") == MANIFEST_SCHEMA_VERSION
        and manifest.get("status") == "success"
        and manifest.get("input_signature") == input_signature
        and manifest.get("output", {}).get("sha256") == output_hash
    )


def _atomic_write_text(path, content):
    temporary_path = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
    except OSError as error:
        raise SkillError("OUTPUT_WRITE_ERROR", f"Failed to write {path}: {error}") from error
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def _replace(template, values):
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{{ " + key + " }}", str(value))
    return rendered


def _open_report(output_file, warnings):
    try:
        if not webbrowser.open(output_file.as_uri()):
            warnings.append({"code": "BROWSER_OPEN_ERROR", "message": "The report was generated but the browser did not open it."})
    except Exception as error:
        warnings.append({"code": "BROWSER_OPEN_ERROR", "message": f"The report was generated but the browser could not open it: {error}"})


async def generate_report(payload):
    config = _validate_payload(payload)
    templates, template_paths = _load_templates()

    text_input_paths = [config["insights_path"], config["transcript_path"], *config["full_transcript_paths"]]
    if config["journey_path"]:
        text_input_paths.append(config["journey_path"])
    total_input_bytes = sum(path.stat().st_size for path in text_input_paths)
    if total_input_bytes > config["max_input_bytes"]:
        raise SkillError(
            "INPUT_TOO_LARGE",
            f"Text inputs total {total_input_bytes} bytes, exceeding max_input_bytes={config['max_input_bytes']}",
        )

    warnings = []
    if total_input_bytes >= config["max_input_bytes"] * INPUT_WARNING_RATIO:
        warnings.append({
            "code": "INPUT_SIZE_WARNING",
            "message": f"Text inputs use {total_input_bytes} of {config['max_input_bytes']} allowed bytes.",
        })

    insights_md = _read_text(config["insights_path"])
    transcript_md = _read_text(config["transcript_path"])
    transcript_headers = extract_transcript_headers(transcript_md)
    if not transcript_headers:
        raise SkillError("PARSING_ERROR", "No interviewee columns were found in mapped-transcript.md")
    if len(transcript_headers) >= LARGE_STUDY_INTERVIEWEE_COUNT:
        warnings.append({
            "code": "LARGE_STUDY_WARNING",
            "message": f"The report contains {len(transcript_headers)} interviewees; wide tables will use horizontal scrolling.",
        })

    try:
        transcript_files = match_full_transcript_inputs(
            [str(path) for path in config["full_transcript_paths"]], transcript_headers
        )
    except (ValueError, OSError, UnicodeError) as error:
        raise SkillError("FULL_TRANSCRIPT_INVALID", str(error)) from error

    ordered_inputs = [
        config["insights_path"],
        config["transcript_path"],
        *[transcript_files[name] for name in transcript_headers],
    ]
    if config["journey_path"]:
        ordered_inputs.append(config["journey_path"])
    input_signature, signature_data = _build_signature(config, ordered_inputs, template_paths)

    if not config["force"] and _current_output_is_valid(
        config["output_file"], config["manifest_file"], input_signature
    ):
        if config["open_browser"]:
            _open_report(config["output_file"], warnings)
        return {
            "status": "skipped",
            "output_file": str(config["output_file"]),
            "manifest_file": str(config["manifest_file"]),
            "input_signature": input_signature,
            "warnings": warnings,
        }

    insights_html_rows, saturation_thead, insight_headers = parse_insights_to_html(insights_md)
    transcript_html_rows, transcript_thead = parse_transcript_to_html(transcript_md)
    if not insights_html_rows.strip() or not insight_headers:
        raise SkillError("PARSING_ERROR", "The Data Saturation Matrix has no renderable insight rows or interviewee headers")
    if not transcript_html_rows.strip():
        raise SkillError("PARSING_ERROR", "The mapped transcript has no renderable data rows")
    if [normalize_interviewee_name(name) for name in insight_headers] != [
        normalize_interviewee_name(name) for name in transcript_headers
    ]:
        raise SkillError("PARSING_ERROR", "Insight and mapped-transcript interviewee columns do not match in order")

    transcript_footer, transcript_drawer = build_full_transcript_ui(
        transcript_headers, transcript_files
    )
    summary_insights_html = extract_summary_insights(insights_md)
    chart_labels, chart_data, total_insights = extract_chart_data(insights_md)
    if total_insights == 0:
        total_insights = insights_html_rows.count("<tr")

    media_stats = await get_media_stats(config["media_paths"])
    journey_rows = (
        '<tr><td colspan="6" class="px-6 py-10 text-center text-sm text-slate-500">'
        'No journey map was supplied for this standalone report.</td></tr>'
    )
    if config["journey_path"]:
        journey_rows = parse_journey_map(_read_text(config["journey_path"], "JOURNEY_ERROR"))
        if not journey_rows.strip():
            raise SkillError("JOURNEY_ERROR", "journey-map.md has no renderable dimension rows")

    overview_module = _replace(templates["overview"], {
        "total_interviewees": len(transcript_headers),
        "total_time_html": media_stats["total_time_html"],
        "total_insights": total_insights,
    })
    saturation_module = _replace(templates["saturation"], {
        "saturation_thead": saturation_thead,
        "insights_rows": insights_html_rows,
        "chart_labels": chart_labels,
        "chart_data": chart_data,
        "total_insights": total_insights,
        "summary_insights_html": summary_insights_html,
    })
    transcript_module = _replace(templates["transcript"], {
        "transcript_thead": transcript_thead,
        "transcript_rows": transcript_html_rows,
        "transcript_footer": transcript_footer,
        "transcript_drawer": transcript_drawer,
    })
    journey_module = _replace(templates["journey"], {"journey_rows": journey_rows})
    final_html = _replace(templates["base"], {
        "overview_module": overview_module,
        "insights_saturation_module": saturation_module,
        "transcript_module": transcript_module,
        "journey_module": journey_module,
        "project_name": html.escape(config["project_name"]),
    })
    unresolved = sorted(set(re.findall(r"{{\s*([a-zA-Z0-9_]+)\s*}}", final_html)))
    if unresolved:
        raise SkillError("TEMPLATE_ERROR", f"Unresolved template placeholders: {', '.join(unresolved)}")

    output_hash = _sha256_bytes(final_html.encode("utf-8"))
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "renderer_version": RENDERER_VERSION,
        "status": "success",
        "input_signature": input_signature,
        "signature_data": signature_data,
        "output": {
            "path": str(config["output_file"]),
            "sha256": output_hash,
            "size": len(final_html.encode("utf-8")),
        },
    }
    _atomic_write_text(config["output_file"], final_html)
    _atomic_write_text(
        config["manifest_file"],
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )

    if config["open_browser"]:
        _open_report(config["output_file"], warnings)
    return {
        "status": "success",
        "output_file": str(config["output_file"]),
        "manifest_file": str(config["manifest_file"]),
        "input_signature": input_signature,
        "warnings": warnings,
    }


async def main():
    try:
        result = await generate_report(_read_payload())
    except SkillError as error:
        print(json.dumps({"status": "error", "code": error.code, "message": error.message}, ensure_ascii=False))
        raise SystemExit(1) from error
    except Exception as error:
        print(json.dumps({
            "status": "error",
            "code": "INTERNAL_ERROR",
            "message": f"Unexpected visualization failure: {error}",
        }, ensure_ascii=False))
        raise SystemExit(1) from error
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(main())
