# Recording media

Every place a clip belongs is marked in the Markdown with an HTML comment saying
what to record:

```html
<!-- media: 10s. Hover across four adjacent faces of a part so the orange
     preview jumps face to face, then click one. -->
```

Grep for `media:` to find them all:

```bash
grep -rn "media:" docs/
```

## Use video, not GIF

**A 10-second GIF weighs 8–15 MB; the same clip in VP9 WebM is around 400 KB.**
Those files live in the git repository forever, so a docs site fed on GIFs turns
into a repository nobody wants to clone.

A plain `<video>` tag works in any MkDocs theme, and the site's stylesheet already
gives it the frame and responsive sizing images get.

## Recording

Record at 1920×1080 and downscale in the encode; recording small and scaling up
never works. Keep clips under 20 seconds and cut anything that is not the thing
being shown.

## Encoding

Trim first, so you are not paying the encoder for frames you throw away:

```bash
ffmpeg -ss 00:00:04 -to 00:00:16 -i raw.mkv -c copy trimmed.mkv
```

Then encode to WebM:

```bash
ffmpeg -i trimmed.mkv -vf "fps=30,scale=1280:-2" -c:v libvpx-vp9 -b:v 0 -crf 34 -row-mt 1 -an docs/assets/video/hover-patches.webm
```

`-crf 34` is a good starting point for viewport footage; drop to 30 if gradients
band, raise to 38 for something mostly static. `-an` strips audio — these clips
are silent and autoplaying, so audio is dead weight the browser still fetches.

Extract a poster frame. It is what shows while the video loads, which on a slow
connection is most of the visit:

```bash
ffmpeg -ss 00:00:01 -i docs/assets/video/hover-patches.webm -frames:v 1 -q:v 3 docs/assets/img/hover-patches.jpg
```

If you need an H.264 fallback for older browsers, `-pix_fmt yuv420p` is not
optional (without it Safari and QuickTime refuse the file) and `+faststart` moves
the index to the front so playback can start before the whole file arrives:

```bash
ffmpeg -i trimmed.mkv -vf "fps=30,scale=1280:-2" -c:v libx264 -crf 24 -preset slow -pix_fmt yuv420p -movflags +faststart -an docs/assets/video/hover-patches.mp4
```

## Embedding

```html
<video autoplay loop muted playsinline
       poster="../assets/img/hover-patches.jpg">
  <source src="../assets/video/hover-patches.webm" type="video/webm">
</video>
```

`muted` is required or the browser will not autoplay at all. `playsinline` stops
iOS taking the video fullscreen. Paths are relative to the **page**, so a page
inside `docs/guide/` needs `../assets/…`.

## Screenshots

PNG for anything with UI text (the N-panel, preferences), JPEG for a viewport
photo. Crop to the subject — a full-screen Blender screenshot scaled to article
width is unreadable.

```bash
ffmpeg -i shot.png -vf "crop=520:900:1400:60" docs/assets/img/panel-patch.png
```

Images get a lightbox automatically, so a full-size screenshot is one click away
even when the article shows it small.

## Where files go

```
docs/assets/img/     screenshots and poster frames
docs/assets/video/   .webm, and .mp4 where a fallback is wanted
```

Name them after the page and the thing shown: `matching-side-colours.webm`,
`panel-patch.png`.

## Checklist

- Under 20 seconds, cropped, no dead time at either end
- Encoded to WebM, well under 1 MB
- Poster frame extracted
- `autoplay loop muted playsinline` all present
- The `<!-- media: … -->` comment it replaces is deleted
- `python -m mkdocs serve` and watch it actually play
