from PIL import Image, ImageFont, ImageDraw
# try a few monospace fonts at small sizes
cands = [
    ("/System/Library/Fonts/Menlo.ttc", 8),
    ("/System/Library/Fonts/Menlo.ttc", 9),
    ("/System/Library/Fonts/Monaco.ttf", 8),
    ("/System/Library/Fonts/SFNSMono.ttf", 8),
]
import os
for path,sz in cands:
    if not os.path.exists(path):
        print(path, "MISSING"); continue
    try:
        f = ImageFont.truetype(path, sz)
    except Exception as e:
        print(path, "ERR", e); continue
    print(f"=== {path} @ {sz} ===")
    for ch in "Aag@e":
        img = Image.new("L",(8,8),0)
        d = ImageDraw.Draw(img)
        d.text((0,-1), ch, fill=255, font=f)
        rows=[]
        for y in range(8):
            rows.append("".join("#" if img.getpixel((x,y))>110 else "." for x in range(8)))
        print(ch, "|"); 
        for r in rows: print("  "+r)
