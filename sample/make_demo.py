"""Build a synthetic narrated demo video (macOS `say` + bundled ffmpeg)."""
import re, subprocess, imageio_ffmpeg
FF = imageio_ffmpeg.get_ffmpeg_exe()
sections = [
 ("Welcome to VidPrep", "#1e3a8a", "Welcome to this demo of VidPrep, a Streamlit app that runs inside Snowflake. In the next few minutes you will see how it turns one uploaded video into chapters, a description, titles, thumbnails, captions, and a frequently asked questions list."),
 ("The publishing problem", "#7c2d12", "Publishing a video takes more work than recording it. You need to write a description, mark chapter timestamps, choose keywords, pick a thumbnail, and prepare captions. Doing all of that by hand can take longer than the edit itself."),
 ("Uploading your video", "#065f46", "The workflow starts with a simple upload. You drop in a video or audio file that you own, and the app saves it to a scratch folder with a unique name. The file contents are hashed so that the same upload can reuse its cached results."),
 ("Transcribing with AI_TRANSCRIBE", "#581c87", "Next, the app stages the media and calls the AI transcribe function with word level timestamps. Every spoken word comes back with a start and end time. Long recordings are split into chunks and stitched back onto one timeline."),
 ("Why timestamps come from code", "#9f1239", "Here is the key design idea. A language model should never invent a timestamp. Instead, the model points at a word index in the real transcript, and the code looks up the exact time for that word. That removes a whole class of hallucinated chapter markers."),
 ("Generating with AI_COMPLETE", "#1e40af", "The AI complete function reads the transcript in overlapping windows and suggests chapter titles, a short description, and search keywords. Responses use a structured JSON format, so the app can validate every field before showing it."),
 ("Titles, thumbnails, and captions", "#92400e", "Each extra feature lives in its own tab. You can generate title ideas with an SEO checklist, extract real thumbnail frames at chapter starts, find quotable moments for social clips, and download caption files in SRT or VTT format."),
 ("Review before you publish", "#134e4a", "Finally, always review the results before you publish. Transcription and generated copy can contain mistakes, so treat everything as a strong first draft. Thanks for watching, and happy publishing."),
]
parts = []
PAD = 0.6  # silence after each section, in seconds


def duration(path):
    err = subprocess.run([FF, "-i", path], capture_output=True, text=True).stderr
    h, m, s = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", err).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


start = 0.0
for i, (title, color, text) in enumerate(sections):
    aiff, mp4 = f"s{i}.aiff", f"s{i}.mp4"
    subprocess.run(["say", "-v", "Samantha", "-r", "175", "-o", aiff, text], check=True)
    # Video and audio get the same explicit length so concatenation cannot drift.
    seconds = round(duration(aiff) + PAD, 2)
    vf = (f"drawtext=text='{title}':fontcolor=white:fontsize=44:x=(w-text_w)/2:y=(h-text_h)/2-20:fontfile=/System/Library/Fonts/Supplemental/Arial Bold.ttf,"
          f"drawtext=text='Part {i+1} of {len(sections)}':fontcolor=white@0.8:fontsize=24:x=(w-text_w)/2:y=(h/2)+50:fontfile=/System/Library/Fonts/Supplemental/Arial.ttf")
    subprocess.run([FF, "-y", "-f", "lavfi", "-i", f"color=c={color}:s=1280x720:r=24", "-i", aiff,
                    "-vf", vf, "-af", f"apad,atrim=0:{seconds}", "-t", str(seconds),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "44100", "-ac", "1", mp4],
                   check=True, capture_output=True)
    print(f"{start:6.2f}s  {title}")
    start += seconds
    parts.append(mp4)
inputs = [arg for p in parts for arg in ("-i", p)]
streams = "".join(f"[{i}:v][{i}:a]" for i in range(len(parts)))
subprocess.run([FF, "-y", *inputs, "-filter_complex", f"{streams}concat=n={len(parts)}:v=1:a=1[v][a]",
                "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                "vidprep_demo.mp4"], check=True, capture_output=True)
print("total", duration("vidprep_demo.mp4"))
