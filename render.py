import os, json, subprocess, asyncio, time, re, urllib.parse, requests, edge_tts
raw = os.environ.get("P_INPUT") or os.environ.get("P_DISPATCH")
d = json.loads(raw)
if not d.get("segments"):
    d["segments"] = []
    for part in str(d.get("script","")).split("|||"):
        tx, im = (part.split("@@",1) + [""])[:2] if "@@" in part else (part, "")
        if len(tx.strip())>2:
            d["segments"].append({"text": tx.strip(), "image": im.strip() or "cinematic abstract background"})
voice = "ar-EG-ShakirNeural"  # deep Egyptian male storyteller (payload voice ignored)
STYLE = "seerah" if "seerah" in str(d.get("style","")).lower() else "story"
if STYLE=="seerah": RATE, PITCH, GAP_S, GAP_C, MUSIC = "-12%", "-6Hz", 0.65, 0.3, 0.0
else: RATE, PITCH, GAP_S, GAP_C, MUSIC = "-10%", "-6Hz", 0.5, 0.25, 0.06
print("STYLE",STYLE,RATE,PITCH)
W, H, FPS, F = 720, 1280, 25, 0.6   # F = crossfade seconds
segs = d["segments"]
os.makedirs("w", exist_ok=True)
def sh(*a): subprocess.check_call(["ffmpeg","-y","-loglevel","error",*a])
def dur(f): return float(subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",f]).decode().strip())
def ts(t): return "%d:%02d:%05.2f"%(int(t//3600),int(t%3600//60),t%60)
def wrap(words):
    lines=[];cur=""
    for w in words:
        if len(cur)+len(w)+1>22 and cur: lines.append(cur);cur=w
        else: cur=(cur+" "+w).strip()
    if cur: lines.append(cur)
    return "\\N".join(lines)
async def tts(text, f, rate=None, pitch=None):
    last=None
    for k,v in enumerate([voice]*8+["ar-SA-HamedNeural"]*3):
        try:
            await edge_tts.Communicate(text, v, rate=rate or RATE, pitch=pitch or PITCH).save(f)
            if os.path.getsize(f)>1000: return v
        except Exception as e:
            last=e; print("tts err",k,v,repr(e)[:80])
        await asyncio.sleep(2+k)
    raise last or RuntimeError("tts failed")

ONES=["صفر","واحد","اتنين","تلاتة","اربعة","خمسة","ستة","سبعة","تمانية","تسعة","عشرة","احداشر","اتناشر","تلتاشر","اربعتاشر","خمستاشر","ستاشر","سبعتاشر","تمنتاشر","تسعتاشر"]
TENS={2:"عشرين",3:"تلاتين",4:"اربعين",5:"خمسين",6:"ستين",7:"سبعين",8:"تمانين",9:"تسعين"}
HUND={1:"مية",2:"ميتين",3:"تلتمية",4:"ربعمية",5:"خمسمية",6:"ستمية",7:"سبعمية",8:"تمنمية",9:"تسعمية"}
def n2w(n):
    if n<20: return ONES[n]
    if n<100:
        o,t=n%10,n//10
        return TENS[t] if o==0 else ONES[o]+" و"+TENS[t]
    if n<1000:
        h,r=divmod(n,100); return HUND[h] if r==0 else HUND[h]+" و"+n2w(r)
    if n<1000000:
        k,r=divmod(n,1000)
        kw="الف" if k==1 else "الفين" if k==2 else (n2w(k)+(" الاف" if k<=10 else " الف"))
        return kw if r==0 else kw+" و"+n2w(r)
    return str(n)
def pct(base,delta): return "%+d%%"%(int(base.replace("%",""))+delta)
def hz(base,delta): return "%+dHz"%(int(base.replace("Hz",""))+delta)
def prosody(c,last_in_sentence,sent_end):
    e=sent_end if last_in_sentence else ","
    if e in "?؟": return pct(RATE,2),hz(PITCH,5)          # rising question
    if e=="!": return pct(RATE,3),hz(PITCH,3)              # energetic
    if e=="…": return pct(RATE,-6),hz(PITCH,-4)            # trailing, slow
    if e==".": return pct(RATE,-4),hz(PITCH,-4)            # falling statement end
    return RATE,hz(PITCH,2)                               # comma: rising, continues
def prep(t):
    t=t.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩","0123456789")).replace("ـ","")
    t=re.sub(r"(\d+)\s*%",lambda m:n2w(int(m.group(1)))+" في المية",t)
    t=re.sub(r"\d+",lambda m:n2w(int(m.group(0))),t)
    return re.sub(r"\s+"," ",t).strip()
def clauses(sn):
    parts=[p.strip() for p in re.split(r"(?<=[،,؛:])\s+",sn) if p.strip()]
    out=[]
    for p in parts:
        if out and len(p.split())<3: out[-1]+=" "+p
        else: out.append(p)
    if len(out)>1 and len(out[0].split())<3: out[1]=out[0]+" "+out[1]; out=out[1:]
    return out
# ---------- narration: per sentence, with pauses
# ---------- Gemini TTS (one call per video), Shakir edge-tts is the fallback
GKEY=os.environ.get("GEMINI_API_KEY","")
sty=str(d.get("style","")).lower()
GSTYLE="seerah" if "seerah" in sty else "mystery" if ("mystery" in sty or "غموض" in sty) else "hakawati"
GV={"hakawati":("Charon","an Egyptian hakawati storyteller by the fire, deep warm voice, slow and dramatic, pauses before suspense, rising on questions"),
    "seerah":("Orus","calm, slow, humble and respectful documentary narration, low steady pitch, long gentle pauses"),
    "mystery":("Algenib","low gravelly voice, mysterious and tense, almost whispering, slow, ending with suspense")}
def gem_tts(text,style,voice):
    body={"model":"gemini-3.8-flash-tts","input":[{"type":"user_input","content":[{"type":"text","text":text,"annotations":[{"type":"speech_metadata","style":style}]}]}],
          "response_format":{"type":"audio"},"generation_config":{"speech_config":[{"voice":voice}]}}
    for k in range(3):
        try:
            r=requests.post("https://generativelanguage.googleapis.com/v1beta/interactions",headers={"x-goog-api-key":GKEY,"Content-Type":"application/json"},json=body,timeout=180)
            print("gemini",r.status_code,flush=True)
            if r.status_code==200:
                data=None
                for s_ in r.json().get("steps",[]):
                    for c_ in s_.get("content",[]):
                        if c_.get("data"): data=c_["data"]
                if data:
                    import base64; open("w/gem.wav","wb").write(base64.b64decode(data)); return True
            else: print("gemini err",r.text[:300].replace(GKEY,"***"))
            if r.status_code in (400,401,403): return False
        except Exception as e: print("gemini exc",repr(e)[:100].replace(GKEY,"***"))
        time.sleep(8*(k+1))
    return False
def gem_narration():
    texts=[prep(re.sub(r"\s+"," ",s["text"]).strip()) for s in segs]
    vo,st=GV[GSTYLE]
    if not gem_tts("\n\n".join(texts),st,vo): return None
    sh("-i","w/gem.wav","-ar","24000","-ac","1","w/gem24.wav")
    T=dur("w/gem24.wav"); n=len(segs); cuts=[0.0]
    if n>1:
        out=subprocess.run(["ffmpeg","-i","w/gem24.wav","-af","silencedetect=n=-38dB:d=0.35","-f","null","-"],capture_output=True,text=True).stderr
        st_=[float(x) for x in re.findall(r"silence_start: ([\d.]+)",out)]; en_=[float(x) for x in re.findall(r"silence_end: ([\d.]+)",out)]
        sil_=[(e-s,(s+e)/2) for s,e in zip(st_,en_) if 0.5<s<T-0.5]
        tot_c=sum(len(t) for t in texts); acc=0; exp=[]
        for t in texts[:-1]: acc+=len(t); exp.append(T*acc/tot_c)
        # for each expected boundary pick the longest silence within 20% of T of it
        for e_ in exp:
            c_=[x for x in sil_ if abs(x[1]-e_)<0.2*T and x[1]>cuts[-1]+1.0]
            cuts.append(max(c_)[1] if c_ else e_)
        print("cuts",[round(x,1) for x in cuts],"of",round(T,1))
    cuts.append(T)
    scenes=[];SS=[];info_all=[]
    for i in range(n):
        a_,b_=cuts[i],cuts[i+1]; tot=(b_-a_)+(0.2 if i==0 else 0)+0.25
        f=f"w/scene{i}.wav"
        sh("-ss",f"{a_:.3f}","-t",f"{b_-a_:.3f}","-i","w/gem24.wav","-af",("adelay=200," if i==0 else "")+"apad","-t",f"{tot:.3f}","-ar","24000","-ac","1",f)
        sents=[x.strip() for x in re.split(r"(?<=[.!?؟…])\s+|\n+",segs[i]["text"].replace("...","…")) if len(x.strip())>1]
        cl=[c for sn in sents for c in clauses(sn)] or [segs[i]["text"]]
        span=tot-0.45-(0.2 if i==0 else 0); tl=sum(len(c) for c in cl) or 1; off=(0.2 if i==0 else 0.0); info=[]
        for c in cl:
            L=span*len(c)/tl; info.append((off,L,c)); off+=L
        scenes.append(f); SS.append(tot); info_all.append(info)
    return scenes,SS,info_all
GEM_OK=False
if GKEY:
    try:
        g=gem_narration()
        if g: scene_wav,S,sent_t=g; GEM_OK=True; print("NARRATION gemini",GSTYLE)
    except Exception as e: print("gemini path failed",repr(e)[:200].replace(GKEY,"***"))
if not GEM_OK: print("NARRATION edge-tts Shakir")
if not GEM_OK:
    sent_t=[]   # per scene: list of (offset, length, text)
    scene_wav=[]; S=[]
    sil=f"w/sil.wav"; sh("-f","lavfi","-i","anullsrc=r=24000:cl=mono","-t",str(GAP_S),sil)
    sil2="w/sil2.wav"; sh("-f","lavfi","-i","anullsrc=r=24000:cl=mono","-t",str(GAP_C),sil2)
    sil3="w/sil3.wav"; sh("-f","lavfi","-i","anullsrc=r=24000:cl=mono","-t",str(GAP_S+0.25),sil3)
    lead=f"w/lead.wav"; sh("-f","lavfi","-i","anullsrc=r=24000:cl=mono","-t","0.2",lead)
    for i,s in enumerate(segs):
        sentences=[x.strip() for x in re.split(r"(?<=[.!?؟…])\s+|\n+", s["text"].replace("...","…")) if len(x.strip())>1]
        parts=[lead]; off=0.2; info=[]
        k=0
        for sn in sentences:
            cl=clauses(sn); se=sn.rstrip()[-1:]
            for ci,c in enumerate(cl):
                mp=f"w/s{i}_{k}.mp3"; wv=f"w/s{i}_{k}.wav"; k+=1
                lastc=(ci==len(cl)-1); r_,p_=prosody(c,lastc,se)
                v=asyncio.run(tts(prep(c),mp,r_,p_)); print("tts",i,k,v,r_,p_,len(c))
                sh("-i",mp,"-ar","24000","-ac","1",wv)
                L=dur(wv)
                if lastc: gl=GAP_S+(0.25 if se=="…" else 0); gap=sil if se!="…" else sil3
                else: gl=GAP_C; gap=sil2
                info.append((off,L,c)); parts+=[wv,gap]; off+=L+gl
        tot=off+0.25
        open(f"w/l{i}.txt","w").write("".join(f"file '{os.path.abspath(p)}'\n" for p in parts))
        sh("-f","concat","-safe","0","-i",f"w/l{i}.txt","-af","apad","-t",f"{tot:.3f}","-ar","24000","-ac","1",f"w/scene{i}.wav")
        scene_wav.append(f"w/scene{i}.wav"); S.append(tot); sent_t.append(info)
open("w/nar.txt","w").write("".join(f"file '{os.path.abspath(p)}'\n" for p in scene_wav))
sh("-f","concat","-safe","0","-i","w/nar.txt","-c","copy","w/nar.wav")
# ---------- images
UA={"User-Agent":"Mozilla/5.0 (shorts-renderer)"}
def poll(prompt,seed):
    u="https://image.pollinations.ai/prompt/"+urllib.parse.quote(prompt+", vertical, high quality, detailed")+f"?width={W}&height={H}&nologo=true&model=flux&seed={seed}"
    r=requests.get(u,timeout=100,headers=UA)
    print("poll",r.status_code,len(r.content),r.text[:100] if r.status_code!=200 else "")
    return r.content if r.status_code==200 and len(r.content)>5000 else None
def commons(prompt):
    q=" ".join(re.findall(r"[A-Za-z]+",prompt)[:4])
    try:
        r=requests.get("https://commons.wikimedia.org/w/api.php",headers=UA,timeout=40,params={"action":"query","generator":"search","gsrsearch":q+" filetype:bitmap","gsrnamespace":6,"gsrlimit":15,"prop":"imageinfo","iiprop":"url|size|mime","iiurlwidth":1280,"format":"json"})
        pages=sorted(r.json().get("query",{}).get("pages",{}).values(),key=lambda p:p.get("index",99))
        for p in pages:
            ii=p["imageinfo"][0]
            if ii["mime"]=="image/jpeg" and ii["height"]>=700 and ii["width"]>=700:
                b=requests.get(ii["thumburl"],headers=UA,timeout=60).content
                if len(b)>10000: print("commons",q,ii["thumburl"]); return b
    except Exception as e: print("commons err",e)
    return None
import zlib
BASE_SEED=zlib.crc32(str(d.get('title','x')).encode())%9000+1   # same seed for all scenes helps keep the same character look
src=[]
last_ok=None
def safe_prompt(p):
    if STYLE!="seerah": return p
    p=re.sub(r"(?i)\b(prophet\w*|muhammad|mohammed|companion\w*|sahaba|face\w*|portrait|close-?up|man|men|woman|women|person|people|boy|girl|child\w*|rider\w*|warrior\w*|soldier\w*)\b","",p)
    return "traditional painted illustration, wide establishing shot, far away, "+re.sub(r"\s+"," ",p).strip()+", empty scene with no people, no faces, no human figures, at most tiny distant silhouettes seen from behind, warm golden light"
def pollx(prompt,seed):
    prompt=safe_prompt(prompt)
    suf=", vertical, high quality, detailed" if STYLE=="seerah" else ", photorealistic cinematic 35mm film still, dark realistic documentary look, natural muted colors, soft film grain, shallow depth of field, no text, no watermark, not a cartoon, not CGI"
    u="https://image.pollinations.ai/prompt/"+urllib.parse.quote(prompt+suf)+f"?width=720&height=1280&nologo=true&model=flux&seed={seed}"
    r=requests.get(u,timeout=100,headers=UA)
    print("poll",r.status_code,len(r.content),r.text[:80] if r.status_code!=200 else "")
    return r.content if r.status_code==200 and len(r.content)>5000 else None, r.status_code
def prep(b,im):
    open("w/raw.bin","wb").write(b)
    try:
        sh("-i","w/raw.bin","-vf",f"crop=iw:ih*0.93:0:0,scale={W*2}:{H*2}:force_original_aspect_ratio=increase,crop={W*2}:{H*2}",im); return True
    except Exception as e:
        print("convert fail",e); return False
for i,s in enumerate(segs):
    im=f"w/i{i}.jpg"; how=""; ok=False
    for k in range(6):
        try: b,code=pollx(s["image"],BASE_SEED+k*5)
        except Exception as e: print("poll err",e); b,code=None,0
        if b and prep(b,im): how="pollinations"; ok=True; break
        time.sleep(47 if code in (429,402) else 25)
    if not ok and last_ok:
        subprocess.check_call(["cp",last_ok,im]); how="reuse-previous"; ok=True
    if not ok:
        b=commons(s["image"])
        if b and prep(b,im): how="commons"; ok=True
    if not ok:
        how="gradient"
        sh("-f","lavfi","-i",f"gradients=s={W*2}x{H*2}:c0=0x1b2a49:c1=0x7a3e65:seed={i}:d=1","-frames:v","1",im)
    if how=="pollinations": last_ok=im
    src.append(how); print("scene",i,"image",how)
    time.sleep(8)
# ---------- Ken Burns clips
MOVES=[
 "z='1+0.0009*on':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2'",
 "z='1.28-0.0009*on':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2'",
 "z=1.25:x='(iw-iw/zoom)*on/{n}':y='ih/2-ih/zoom/2'",
 "z=1.25:x='(iw-iw/zoom)*(1-on/{n})':y='ih/2-ih/zoom/2'",
 "z=1.25:x='iw/2-iw/zoom/2':y='(ih-ih/zoom)*on/{n}'",
 "z='1+0.0009*on':x='(iw-iw/zoom)*on/{n}':y='(ih-ih/zoom)*(1-on/{n})'",
]
clips=[]; D=[]
for i in range(len(segs)):
    Di=S[i]+(F if i<len(segs)-1 else 0); D.append(Di); n=int(Di*FPS)
    mv=MOVES[i%len(MOVES)].replace("{n}",str(n))
    sh("-loop","1","-framerate",str(FPS),"-i",f"w/i{i}.jpg","-t",f"{Di:.2f}","-vf",f"zoompan={mv}:d=1:s={W}x{H}:fps={FPS},format=yuv420p","-c:v","libx264","-preset","veryfast","-an",f"w/v{i}.mp4")
    clips.append(f"w/v{i}.mp4")
# ---------- subtitles
ass=[]; start=0.0
for i,info in enumerate(sent_t):
    for off,L,sn in info:
        words=sn.split(); chunks=[words[j:j+4] for j in range(0,len(words),4)]
        tot=sum(len(" ".join(c)) for c in chunks); tt=start+off
        for c in chunks:
            l=L*len(" ".join(c))/tot
            ass.append(f"Dialogue: 0,{ts(tt)},{ts(tt+l)},C,,0,0,0,,{wrap([x for x in c]).rstrip(chr(46)+chr(1548)+chr(44))}"); tt+=l
    start+=S[i]
hdr="[Script Info]\nScriptType: v4.00+\nPlayResX: 720\nPlayResY: 1280\n[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\nStyle: C,Noto Sans Arabic,46,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,4,1,2,40,40,260,1\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
open("c.ass","w",encoding="utf-8").write(hdr+"\n".join(ass)+"\n")
# ---------- music (synthesized soft ambient pad, own work, no licence issue)
total=sum(S)
sh("-f","lavfi","-i",f"sine=f=146.83:r=44100:d={total+1}","-f","lavfi","-i",f"sine=f=220:r=44100:d={total+1}","-f","lavfi","-i",f"sine=f=261.63:r=44100:d={total+1}","-f","lavfi","-i",f"sine=f=329.63:r=44100:d={total+1}",
   "-filter_complex","amix=inputs=4:normalize=0,lowpass=f=900,tremolo=f=0.25:d=0.5,volume=0.5,afade=t=in:d=2,afade=t=out:st=%.2f:d=2"%(total-2),"w/music.wav")
# ---------- final mux
ins=[]; 
for c in clips: ins+=["-i",c]
n=len(clips)
fc=""; prev="[0:v]"; acc=D[0]
for k in range(1,n):
    off=acc-F; fc+=f"{prev}[{k}:v]xfade=transition=fade:duration={F}:offset={off:.3f}[x{k}];"; prev=f"[x{k}]"; acc=off+D[k]
fc+=f"{prev}ass=c.ass[v];" if n>1 else "[0:v]ass=c.ass[v];"
fc+=f"[{n}:a]volume=1.0[na];[{n+1}:a]volume={MUSIC}[ma];[na][ma]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-16:TP=-1.5[a]"
sh(*ins,"-i","w/nar.wav","-i","w/music.wav","-filter_complex",fc,"-map","[v]","-map","[a]","-c:v","libx264","-preset","veryfast","-crf","24","-c:a","aac","-b:a","128k","-movflags","+faststart","-shortest","out.mp4")
print("images",src,"size MB",os.path.getsize("out.mp4")/1e6,"dur",dur("out.mp4"),"narr",dur("w/nar.wav"))
open("dur.txt","w").write(str(dur("out.mp4")))
json.dump({"callback":d.get("callback"),"chat_id":d.get("chat_id"),"title":d.get("title","")},open("meta.json","w"))
