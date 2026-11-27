import os, json, base64, subprocess, requests, sys
KEY = os.environ["GEMINI_API_KEY"]
MODEL = os.environ.get("GMODEL", "gemini-3.8-flash-tts")
CB = "https://essam-assistant.app.n8n.cloud/webhook/vd-b10133bdad197e23"
TEXT = ("في ليلة من ليالي الشتا، كان فيه راجل عجوز قاعد قدّام بيته. "
        "بص للسما وقال: النجوم دي شاهدة على حكايات كتير. "
        "وفجأة سمع خطوات بتقرّب من بعيد... مين اللي جاي في الوقت ده؟")
STYLES = [
 ("hakawati", "حكاية شعبية", "Charon", "an Egyptian hakawati storyteller by the fire, deep warm voice, slow and dramatic, pauses before suspense, rising on questions"),
 ("seerah", "سيرة هادئة", "Orus", "calm, slow, humble and respectful documentary narration, low steady pitch, long gentle pauses"),
 ("mystery", "غموض", "Algenib", "low gravelly voice, mysterious and tense, almost whispering, slow, ending with suspense"),
]
only = sys.argv[1:] 
for k, title, voice, style in STYLES:
    if only and k not in only: continue
    body = {"model": MODEL,
        "input": [{"type":"user_input","content":[{"type":"text","text":TEXT,"annotations":[{"type":"speech_metadata","style":style}]}]}],
        "response_format": {"type":"audio"},
        "generation_config": {"speech_config":[{"voice":voice}]}}
    r = requests.post("https://generativelanguage.googleapis.com/v1beta/interactions",
        headers={"x-goog-api-key":KEY,"Content-Type":"application/json"}, json=body, timeout=180)
    print(k, "status", r.status_code, flush=True)
    if r.status_code != 200:
        print(k, "ERR", r.text[:600].replace(KEY,"***"), flush=True); continue
    j = r.json(); data = None
    for s in j.get("steps", []):
        for c in s.get("content", []):
            if c.get("data"): data = c["data"]
    if not data:
        print(k, "no audio, keys:", list(j.keys()), str(j)[:400], flush=True); continue
    open(f"{k}.wav","wb").write(base64.b64decode(data))
    subprocess.run(["ffmpeg","-y","-loglevel","error","-f","lavfi","-i","color=c=0x15151f:s=720x1280:r=15","-i",f"{k}.wav",
        "-af","loudnorm=I=-16:TP=-1.5:LRA=11","-c:v","libx264","-pix_fmt","yuv420p","-c:a","aac","-shortest",f"{k}.mp4"],check=True)
    dur = float(subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",f"{k}.mp4"]).decode())
    print(k, "duration", round(dur,1), flush=True)
    open("done.txt","a").write(f"{k}|{title}|{dur:.1f}\n")
