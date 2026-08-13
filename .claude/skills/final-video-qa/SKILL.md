---
name: final-video-qa
description: Checking the finished mp4 before calling a video done — every scene has audio, captions are timed, cards rendered, duration matches intent, and the music does not fight the narration. Use after pipeline.assemble, before showing a video to anyone, or when a finished video looks or sounds wrong. Triggers include final.mp4, video looks wrong, silent scene, missing audio, captions missing, wrong music, verify video, is the video good, after assemble.
---

# Checking the finished video

`images-director` checks the **source images**. This checks the **assembled
result**, where different things go wrong: audio that never generated, captions
that did not burn in, a card that rendered black, music from the wrong mood.
Every command below was run against a real video in this repo.

## Do not spot-check

Reported on *The Thirsty Crow*: images were declared good after two of five
scenes were examined. The scene never opened — scene 0, the **opening frame** —
had a girl in a field and no crow. It shipped into an assembled video that was
reported as fixed, twice.

**Look at every scene, every time.** It costs one command.

## 1. Every scene, in one image

    cd output/<name>
    ffmpeg -y -i clips/scene_%02d.mp4 -filter_complex "scale=640:360,tile=3x2" sheet.png

Use `clips/`, not `images/` — clips carry the overlays, captions and Ken Burns
crop, so this is what the viewer sees. Raise the grid for more scenes.

Read it asking:
- Is anything here the story never mentioned? (see `image-prompt`)
- Is the subject present at all?
- Are captions legible against the image? Dark text on a bright frame is a
  palette bug — see `_burn_in_colour` in `assemble.py`.
- Did every card render, or is one a black frame?

## 2. Audio on every scene

A scene whose voiceover failed still assembles — it just goes silent.

    for f in audio/scene_*.mp3; do
      d=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f")
      peak=$(ffmpeg -hide_banner -i "$f" -af volumedetect -f null - 2>&1 \
             | grep max_volume | awk '{print $5,$6}')
      printf "  %-22s %5.1fs  peak %s\n" "$f" "$d" "$peak"
    done

Expect one mp3 per scene, none near 0.0s, peaks around −2 to −5 dB. A missing
file or a silent one means that scene's TTS failed — see `voiceover-director`
for the per-scene retry.

## 3. Captions exist for every scene

Captions come from `.words.json`, which only edge-tts `WordBoundary` produces.
No word timings means no captions, silently.

    for f in audio/scene_*.srt; do
      [ -s "$f" ] && echo "  $f: $(grep -c ' --> ' "$f") chunks" || echo "  $f: EMPTY"
    done

Any `EMPTY` on a scene with narration is a defect.

## 4. Duration against intent

    python - <<'EOF'
    import json, subprocess
    d = json.load(open("shot_plan.json"))
    n = len(d["scenes"])
    real = float(subprocess.run(
        ["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0","final.mp4"],
        capture_output=True, text=True).stdout)
    print(f"{n} scenes, {real:.1f}s -> {real/n:.1f}s per scene (prompt targets 4-8s)")
    EOF

Per-scene well under 4s means the narration is too thin for the scene count;
well over 8s means scenes are doing too much. Scene durations are measured from
the mp3s, never from the plan — the plan cannot be wrong about length, only the
narration can.

## 5. The music

Re-read the assemble header rather than guessing:

- `RANDOM FALLBACK` → the mood missed and the track is unrelated to the video.
  Fix in `music-bed` (alias or folder), then re-assemble — free.
- A matched mood that still fights the video is a plan problem: revise
  `music_mood`, do not hand-pick around it.

## Before you call it done

- [ ] contact sheet read — every scene, nothing invented, subject present
- [ ] one mp3 per scene, none silent
- [ ] captions present wherever there is narration
- [ ] per-scene duration inside 4-8s
- [ ] music matched its mood, no `RANDOM FALLBACK`
- [ ] cards rendered (not black frames)

Re-assembly is free and local. Everything on this list except regenerating an
image costs nothing to fix, so there is no reason to ship a video that fails it.
