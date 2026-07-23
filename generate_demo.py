import os
import subprocess
import json

desktop_dir = os.path.expanduser("~/Desktop")
demo_dir = os.path.join(desktop_dir, "Demo_6_Users")
os.makedirs(demo_dir, exist_ok=True)

insights_path = os.path.join(demo_dir, "insights.md")
transcript_path = os.path.join(demo_dir, "mapped-transcript.md")

insights_content = """# Insights — Alice
| # | Insight | Quotes |
|---|---|---|
| 1 | Navigation is confusing | "I couldn't find the settings menu at all." |
| 2 | Fast loading time | "It opened instantly, which was great." |

# Insights — Bob
| # | Insight | Quotes |
|---|---|---|
| 1 | Navigation is confusing | "Too many buttons on the home screen." |
| 2 | Likes the color scheme | "The blue and white looks very professional." |

# Insights — Charlie
| # | Insight | Quotes |
|---|---|---|
| 1 | Navigation is confusing | "Where do I go to change my profile picture?" |
| 2 | Needs offline mode | "I lost connection and the app crashed." |

# Insights — Diana
| # | Insight | Quotes |
|---|---|---|
| 1 | Fast loading time | "Everything snaps into place immediately." |
| 2 | Needs offline mode | "I travel a lot, offline access is crucial." |

# Insights — Eve
| # | Insight | Quotes |
|---|---|---|
| 1 | Navigation is confusing | "Menu is hidden behind a swipe I didn't know about." |
| 2 | Likes the color scheme | "Very easy on the eyes." |

# Insights — Frank
| # | Insight | Quotes |
|---|---|---|
| 1 | Navigation is confusing | "I spent 5 minutes looking for the logout button." |
| 2 | Fast loading time | "Zero lag, I love it." |

## Summary of Discovered Insights
- **Navigation is confusing**: The majority of users struggled with finding core features.
- **Fast loading time**: Users consistently praised the app's responsiveness.
- **Likes the color scheme**: The visual design is well-received.
- **Needs offline mode**: A requested feature for traveling users.

# Data Saturation Matrix
| Insight | Alice | Bob | Charlie | Diana | Eve | Frank |
|---|---|---|---|---|---|---|
| Navigation is confusing | 🔵 | 🌐 | 🌐 | ⚪️ | 🌐 | 🌐 |
| Fast loading time | 🔵 | ⚪️ | ⚪️ | 🌐 | ⚪️ | 🌐 |
| Likes the color scheme | ⚪️ | 🔵 | ⚪️ | ⚪️ | 🌐 | ⚪️ |
| Needs offline mode | ⚪️ | ⚪️ | 🔵 | 🌐 | ⚪️ | ⚪️ |

## Data Saturation Chart
| Insight Category | Alice | Bob | Charlie | Diana | Eve | Frank |
|---|---|---|---|---|---|---|
| **🔵 New Insights** | 2 | 1 | 1 | 0 | 0 | 0 |
"""

transcript_content = """| # | Topic | Question | Observed Variable | Alice | Bob | Charlie | Diana | Eve | Frank |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Usability | How easy was it to navigate? | Navigation | Confusing | Too many buttons | Hard to find profile | Okay | Hidden menus | Couldn't logout |
| 2 | Performance | What do you think about the speed? | Loading Time | Instant | Good | Normal | Snappy | Fast | Zero lag |
| 3 | Design | How do you feel about the colors? | Aesthetics | N/A | Professional | Okay | Fine | Easy on eyes | Good |
| 4 | Features | What feature is missing? | Requests | Nothing | None | Offline mode | Offline access | Not sure | N/A |
"""

with open(insights_path, "w", encoding="utf-8") as f:
    f.write(insights_content)

with open(transcript_path, "w", encoding="utf-8") as f:
    f.write(transcript_content)

print(f"Created {insights_path}")
print(f"Created {transcript_path}")

# Run the visualization script
viz_script = os.path.expanduser(
    "~/Desktop/UX Agent/.agents/workflows/ux-research/skills/"
    "visualize-insights/scripts/visualize_insights.py"
)
input_json = json.dumps({
    "insights_path": insights_path,
    "transcript_path": transcript_path,
    "output_dir": demo_dir,
    "project_name": "Demo_6_Users_Dashboard"
})

print(f"Running visualization script...")
subprocess.run(["python3", viz_script, input_json], check=True)
print(f"Successfully generated Demo_6_Users_Dashboard.html in {demo_dir}")
