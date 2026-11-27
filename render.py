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
RATE, PITCH = "+0%", "-8Hz"
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
async def tts(text, f):
    last=None
    for k,v in enumerate([voice]*8+["ar-SA-HamedNeural"]*3):
        try:
            await edge_tts.Communicate(text, v, rate=RATE, pitch=PITCH).save(f)
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
sent_t=[]   # per scene: list of (offset, length, text)
scene_wav=[]; S=[]
sil=f"w/sil.wav"; sh("-f","lavfi","-i","anullsrc=r=24000:cl=mono","-t","0.4",sil)
sil2="w/sil2.wav"; sh("-f","lavfi","-i","anullsrc=r=24000:cl=mono","-t","0.2",sil2)
lead=f"w/lead.wav"; sh("-f","lavfi","-i","anullsrc=r=24000:cl=mono","-t","0.2",lead)
for i,s in enumerate(segs):
    sentences=[x.strip() for x in re.split(r"(?<=[.!?؟…])\s+|\n+", s["text"]) if len(x.strip())>1]
    parts=[lead]; off=0.2; info=[]
    k=0
    for sn in sentences:
        cl=clauses(sn)
        for ci,c in enumerate(cl):
            mp=f"w/s{i}_{k}.mp3"; wv=f"w/s{i}_{k}.wav"; k+=1
            v=asyncio.run(tts(prep(c),mp)); print("tts",i,k,v,len(c))
            sh("-i",mp,"-ar","24000","-ac","1",wv)
            L=dur(wv); gap=sil if ci==len(cl)-1 else sil2; gl=0.4 if ci==len(cl)-1 else 0.2
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
src=[]
last_ok=None
def pollx(prompt,seed):
    u="https://image.pollinations.ai/prompt/"+urllib.parse.quote(prompt+", vertical, high quality, detailed")+f"?width=576&height=1024&nologo=true&model=flux&seed={seed}"
    r=requests.get(u,timeout=70,headers=UA)
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
        try: b,code=pollx(s["image"],i*13+k*5+1)
        except Exception as e: print("poll err",e); b,code=None,0
        if b and prep(b,im): how="pollinations"; ok=True; break
        time.sleep(46 if code==429 else 25)
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
fc+=f"[{n}:a]volume=1.0[na];[{n+1}:a]volume=0.07[ma];[na][ma]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-16:TP=-1.5[a]"
sh(*ins,"-i","w/nar.wav","-i","w/music.wav","-filter_complex",fc,"-map","[v]","-map","[a]","-c:v","libx264","-preset","veryfast","-crf","24","-c:a","aac","-b:a","128k","-movflags","+faststart","-shortest","out.mp4")
print("images",src,"size MB",os.path.getsize("out.mp4")/1e6,"dur",dur("out.mp4"),"narr",dur("w/nar.wav"))
open("dur.txt","w").write(str(dur("out.mp4")))
json.dump({"callback":d.get("callback"),"chat_id":d.get("chat_id"),"title":d.get("title","")},open("meta.json","w"))
