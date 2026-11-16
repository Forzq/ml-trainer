# Marin Kitagawa trainer portrait

Character: Marin Kitagawa from *My Dress-Up Darling*.
Character design reference: [official anime character page](https://bisquedoll-anime.com/1st/character/).

All seven PNGs were generated with the built-in `image_gen` tool; no screenshots from the series are bundled. `base.png` was generated from a character description. Each subsequent image was an edit referencing that same base. The normalized base brief and exact edit prompts are stored in [prompts.json](prompts.json).

The immutable base is the only full portrait displayed by the app. Other PNGs supply small masked eye or mouth regions through `PortraitRig`. Their clothing and body pixels never replace the base. `manifest.json` contains source/target coordinates that align the differently sized mouth and supportive-expression sources. No image-generation service runs during training.

- `base.png`: neutral closed-mouth portrait and fixed body plate.
- `mouth-open.png`: talking mouth source.
- `listening.png`, `thinking.png`, `positive.png`, `supportive.png`: eye-expression sources.
- `blink.png`: closed-eyelid source.

The outfit, camera position and pose remain constant in the renderer. The app adds a subtle breathing transform, randomized blinking and audio-driven mouth movement. This is a sprite-based portrait, not a Live2D model or phoneme recognizer.
