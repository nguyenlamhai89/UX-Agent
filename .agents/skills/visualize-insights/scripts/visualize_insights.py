import os
import sys
import json
import asyncio
import re
import glob
import subprocess
from pathlib import Path
import webbrowser

try:
    from google.antigravity import Agent, LocalAgentConfig
except Exception:
    Agent = None
    LocalAgentConfig = None

import shutil

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

async def get_folder_stats(output_dir):
    exts = ['*.mp3', '*.wav', '*.m4a', '*.qta', '*.mp4', '*.mkv', '*.ogg', '*.flac']
    audio_files = []
    
    audio_dir = output_dir
    if os.path.basename(output_dir) == "Interview":
        audio_dir = os.path.dirname(output_dir)
        
    for ext in exts:
        audio_files.extend(glob.glob(os.path.join(audio_dir, ext)))
        audio_files.extend(glob.glob(os.path.join(audio_dir, ext.upper())))
    
    unique_files = sorted(list(set(audio_files)))
    total_interviewees = len(unique_files)
    audio_names = [os.path.splitext(os.path.basename(f))[0] for f in unique_files]
    
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
        "total_interviewees": total_interviewees,
        "total_time_html": total_time_html,
        "audio_names": audio_names
    }

def render_inline_markdown(text):
    if not text or text == "N/A": return ""
    # Bold
    text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)
    # Italic
    text = re.sub(r'\*(.*?)\*', r'<em>\1</em>', text)
    # Links
    text = re.sub(r'\[(.*?)\]\((.*?)\)', r'<a href="\2" class="text-blue-600 hover:underline hover:text-blue-800" target="_blank">\1</a>', text)
    return text

def parse_transcript_to_html(md_text, audio_names=None):
    rows = []
    lines = md_text.split('\n')
    header_found = False
    headers = []
    for line in lines:
        if line.strip().startswith('|'):
            if '---' in line:
                continue
            if not header_found and ('theme' in line.lower() or 'topic' in line.lower()) and 'question' in line.lower():
                header_found = True
                cols = [c.strip() for c in line.strip().strip('|').split('|')]
                headers = cols[4:] if len(cols) > 4 else []
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
                theme = cols[1]
                question = cols[2]
                obs = cols[3]
                
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
                
    if audio_names:
        for i, name in enumerate(audio_names):
            if i < len(headers):
                headers[i] = name
            else:
                headers.append(name)
                
    transcript_thead = f"""
                                        <th scope="col" class="px-2 py-3 text-center text-xs font-medium text-slate-500 uppercase tracking-wider w-1 whitespace-nowrap">#</th>
                                        <th scope="col" class="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider w-48">Theme</th>
                                        <th scope="col" class="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider w-64">Question</th>
                                        <th scope="col" class="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider w-48">Observed Variable</th>
"""
    for user in headers:
        initial = user[0].upper() if user else "U"
        transcript_thead += f"""
                                        <th scope="col" class="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider min-w-[300px]">
                                            <div class="flex items-center">
                                                <div class="w-6 h-6 rounded-full bg-slate-200 text-slate-600 flex items-center justify-center font-bold text-xs mr-2">{initial}</div>
                                                {user}
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

                    user_name = headers[i] if i < len(headers) else ""
                    # Look up the quote from the per-interviewee section
                    quote_text = quotes_lookup.get(insight, {}).get(user_name, "")

                    if marker and marker not in ("N/A", "", "-"):
                        if quote_text:
                            tds += f"""
                        <td class="p-0 align-top">
                            <button onclick="toggleQuote('insight-{unique_id}')" class="w-full h-full min-h-[60px] flex flex-col items-center justify-start p-3 transition-all focus:outline-none focus:ring-2 focus:ring-blue-500/50">
                                <div id="icon-insight-{unique_id}" class="text-blue-500 text-xl transition-all duration-300">{marker}</div>
                                <div id="quote-insight-{unique_id}" class="hidden w-full mt-2 text-left text-[14px] text-slate-700 italic bg-blue-50 p-3 rounded-md border-l-2 border-blue-400 shadow-sm relative before:absolute before:-top-2 before:left-1/2 before:-translate-x-1/2 before:border-4 before:border-transparent before:border-b-blue-400">
                                    {quote_text}
                                </div>
                            </button>
                        </td>"""
                        else:
                            # Marker exists but no quote found
                            tds += f"""
                        <td class="px-4 py-4 align-top text-center">
                            <span class="text-xl">{marker}</span>
                        </td>"""
                        unique_id += 1
                    else:
                        tds += f"""
                        <td class="px-4 py-4 align-top border-l border-dashed border-slate-200 bg-slate-50/30 group-hover:bg-transparent text-center"><span class="text-slate-300 text-xl">-</span></td>"""

                rows.append(f"""
                <tr class="hover:bg-slate-100 transition-colors group">
                    <td class="px-2 py-4 whitespace-nowrap text-sm text-slate-500 font-medium align-top text-center w-1">{row_num}</td>
                    <td class="px-4 py-4 text-sm text-slate-800 font-medium leading-relaxed align-top">{insight}</td>
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
        initial = user[0].upper() if user else "U"
        saturation_thead += f"""
                                        <th scope="col" class="px-4 py-3 text-center text-xs font-medium text-slate-500 uppercase tracking-wider min-w-[200px]">
                                            <div class="flex flex-col items-center">
                                                <div class="w-8 h-8 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center font-bold mb-1 shadow-sm">{initial}</div>
                                                {user}
                                            </div>
                                        </th>
"""
    return "\n".join(rows), saturation_thead, headers

def extract_chart_data(insights_md, audio_names=None):
    lines = insights_md.split('\n')
    data = []
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
                    data.append(int(val))
                except ValueError:
                    pass
            break

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
    return json.dumps(labels), json.dumps(data), max(data) if data else 0

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
                dimension = dimension.replace('**', '').strip()
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

async def main():
    input_str = ""
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg.endswith('.json') and os.path.exists(arg):
            with open(arg, "r", encoding="utf-8") as f:
                input_str = f.read()
        else:
            input_str = arg
    else:
        if not sys.stdin.isatty():
            input_str = sys.stdin.read()
            
    if not input_str:
        print(json.dumps({"status": "error", "message": "Missing input JSON from arguments, file, or stdin"}))
        sys.exit(1)
        
    try:
        input_data = json.loads(input_str)
    except json.JSONDecodeError:
        print(json.dumps({"status": "error", "message": "Invalid input JSON"}))
        sys.exit(1)
        
    insights_path = input_data.get("insights_path")
    transcript_path = input_data.get("transcript_path")
    output_dir = input_data.get("output_dir")
    project_name = input_data.get("project_name", "Insights_Dashboard")
    journey_path = input_data.get("journey_path")
    
    if not all([insights_path, transcript_path, output_dir]):
        print(json.dumps({"status": "error", "message": "Missing required fields (insights_path, transcript_path, output_dir)"}))
        sys.exit(1)
        
    try:
        with open(insights_path, "r", encoding="utf-8") as f:
            insights_md = f.read()
        with open(transcript_path, "r", encoding="utf-8") as f:
            transcript_md = f.read()
    except Exception as e:
        print(json.dumps({"status": "error", "message": f"Failed to read input files: {str(e)}"}))
        sys.exit(1)
        
    skill_dir = Path(__file__).parent.parent
    template_dir = skill_dir / "template"
    try:
        with open(template_dir / "insights-template.html", "r", encoding="utf-8") as f:
            base_template = f.read()
        with open(template_dir / "modules" / "overview.html", "r", encoding="utf-8") as f:
            overview_module = f.read()
        with open(template_dir / "modules" / "saturation.html", "r", encoding="utf-8") as f:
            saturation_module = f.read()
    except Exception:
        # Fallback to older name if it exists
        try:
            with open(template_dir / "modules" / "insights-saturation.html", "r", encoding="utf-8") as f:
                saturation_module = f.read()
        except Exception:
            saturation_module = ""
            
    try:
        with open(template_dir / "modules" / "transcript.html", "r", encoding="utf-8") as f:
            transcript_module = f.read()
        with open(template_dir / "modules" / "journey-map.html", "r", encoding="utf-8") as f:
            journey_module = f.read()
    except Exception as e:
        # If journey module is missing, it's fine for backward compatibility, but we should capture the rest
        try:
            journey_module = ""
        except Exception:
            pass
    except Exception as e:
        print(json.dumps({"status": "error", "message": f"Failed to read HTML templates: {str(e)}"}))
        sys.exit(1)

    # 1. Fetch stats and audio names first
    stats = await get_folder_stats(output_dir)
    audio_names = stats.get("audio_names", [])

    # 2. Deterministic Python Parsing for Zero Data Loss
    insights_html_rows, saturation_thead, headers = parse_insights_to_html(insights_md, audio_names)
    transcript_html_rows, transcript_thead = parse_transcript_to_html(transcript_md, audio_names)
    summary_insights_html = extract_summary_insights(insights_md)
    chart_labels, chart_data, total_insights = extract_chart_data(insights_md, audio_names)

    # Update total insights from the chart data max value
    stats["total_insights"] = total_insights
    
    # If parsing found 0 insights, fallback to the parsing calculation
    if stats["total_insights"] == 0 and len(insights_html_rows) > 0:
        stats["total_insights"] = len(insights_html_rows.split("</tr>")) - 1

    # Fix total interviewees if audio files were missing but markdown had headers
    if stats["total_interviewees"] == 0 and headers:
        stats["total_interviewees"] = len(headers)

    # 3. Inject modules into base template
    final_html = base_template.replace("{{ overview_module }}", overview_module)
    final_html = final_html.replace("{{ insights_saturation_module }}", saturation_module)
    final_html = final_html.replace("{{ transcript_module }}", transcript_module)
    
    # 4. Replace variables
    final_html = final_html.replace("{{ insights_rows }}", insights_html_rows)
    final_html = final_html.replace("{{ saturation_thead }}", saturation_thead)
    
    final_html = final_html.replace("{{ transcript_rows }}", transcript_html_rows)
    final_html = final_html.replace("{{ transcript_thead }}", transcript_thead)
    
    final_html = final_html.replace("{{ chart_labels }}", chart_labels)
    final_html = final_html.replace("{{ chart_data }}", chart_data)
    
    final_html = final_html.replace("{{ total_interviewees }}", str(stats.get("total_interviewees", 1)))
    final_html = final_html.replace("{{ total_time_html }}", str(stats.get("total_time_html", "")))
    final_html = final_html.replace("{{ total_insights }}", str(stats.get("total_insights", 0)))
    final_html = final_html.replace("{{ summary_insights_html }}", summary_insights_html)
    final_html = final_html.replace("{{ project_name }}", project_name)
    
    journey_nav_class = 'flex items-center px-3 py-2 text-sm font-medium rounded-md text-slate-400 hover:text-slate-600 cursor-not-allowed'
    journey_icon_class = 'w-5 h-5 mr-3 text-slate-300'
    journey_nav_badge = '<span class="ml-auto bg-slate-100 text-slate-500 text-[10px] px-2 py-0.5 rounded-full">Soon</span>'
    journey_module_html = ""
    
    if journey_path and os.path.exists(journey_path):
        try:
            with open(journey_path, "r", encoding="utf-8") as f:
                journey_md = f.read()
            journey_rows = parse_journey_map(journey_md)
            if journey_module:
                journey_module_html = journey_module.replace("{{ journey_rows }}", journey_rows)
            
            # Activate Nav
            journey_nav_class = 'flex items-center px-3 py-2 text-sm font-medium rounded-md text-slate-700 hover:text-blue-600 hover:bg-blue-50 transition-colors'
            journey_icon_class = 'w-5 h-5 mr-3 text-slate-400 group-hover:text-blue-500 transition-colors'
            journey_nav_badge = ''
        except Exception as e:
            print(f"Warning: Failed to parse journey map: {e}")
            
    final_html = final_html.replace("{{ journey_nav_class }}", journey_nav_class)
    final_html = final_html.replace("{{ journey_icon_class }}", journey_icon_class)
    final_html = final_html.replace("{{ journey_nav_badge }}", journey_nav_badge)
    final_html = final_html.replace("{{ journey_module }}", journey_module_html)
    
    try:
        os.makedirs(output_dir, exist_ok=True)
        output_file = os.path.join(output_dir, f"{project_name}.html")
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(final_html)
            
        webbrowser.open(f'file://{output_file}')
        print(json.dumps({"status": "success", "output_file": output_file}))
    except Exception as e:
        print(json.dumps({"status": "error", "message": f"Failed to write output file: {str(e)}"}))
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
