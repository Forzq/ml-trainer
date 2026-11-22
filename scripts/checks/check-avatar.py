"""Exercise uploaded avatar frames and audio-driven mouths without external APIs."""
import argparse
import base64
import faulthandler
import io
import json
import math
import socket
import struct
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import uvicorn
from app.questions.catalog import load_cards
from app.core.config import Settings
from app.server import create_app


def wait(evaluate, expression, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if evaluate(expression): return
        except Exception as error:
            if not any(text in str(error) for text in ("Execution context was destroyed", "is not defined")):
                raise
        time.sleep(.04)
    raise AssertionError("Avatar check timed out: " + expression)


def checks(evaluate, audio=None, screenshot=None):
    wait(evaluate, "Boolean(state.config && document.querySelector('.hero'))")
    print("Avatar check: interface loaded", flush=True)
    sample = io.BytesIO()
    with wave.open(sample, "wb") as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000)
        wav.writeframes(b"".join(struct.pack("<h", int(11000 * math.sin(2 * math.pi * 220 * n / 24000)))
                                if (n // 6000) % 2 == 0 else b"\0\0" for n in range(72000)))
    encoded = base64.b64encode(sample.getvalue()).decode()
    evaluate("""(() => {
        window.avatarCheckErrors=[];
        addEventListener('error', e => avatarCheckErrors.push(e.message));
        addEventListener('unhandledrejection', e => avatarCheckErrors.push(String(e.reason)));
        state.sound=false; state.config.tts={provider:'fish',ready:true}; syncVoiceControls();
        showStart('classical_ml'); document.querySelector('#start-form').requestSubmit(); return true;
    })()""")
    wait(evaluate, "Boolean(document.querySelector('#trainer-avatar'))")
    evaluate("document.querySelector('#trainer-avatar [data-action=avatar-settings]').click(); true")
    wait(evaluate, "document.activeElement?.id==='settings-avatar'")
    assert evaluate("document.querySelector('#avatar-preset').options.length===1 && document.querySelector('#avatar-preset').value==='marin'")
    assert evaluate("!document.querySelector('#avatar-settings input[type=file], #avatar-preset-info')")
    evaluate("document.querySelector('#settings-resume').click(); true")
    wait(evaluate, "Boolean(document.querySelector('#trainer-avatar'))")
    if screenshot: screenshot()
    print("Avatar check: built-in avatar settings passed", flush=True)
    evaluate("""(() => {
        window.avatarTestFetch=window.fetch;
        window.fetch=(input, options)=>String(input).includes('/api/speech')
            ? Promise.resolve(new Response(Uint8Array.from(atob('%s'), c=>c.charCodeAt(0)),{headers:{'Content-Type':'audio/wav'}}))
            : avatarTestFetch(input, options);
        window.avatarSeen=[];
        window.avatarWatch=setInterval(()=>{
            if (speech.status==='playing') avatarSeen.push(document.querySelector('#trainer-avatar').dataset.mouth);
        },30);
        setVolume(15); speak('Test audio',{force:true}); return true;
    })()""" % encoded)
    wait(evaluate, "speech.status==='playing' && avatarSeen.includes('open') && avatarSeen.includes('closed')")
    assert evaluate("trainerAvatar.context.state==='running' && !speech.audio.paused")
    wait(evaluate, "speech.status==='idle'")
    assert evaluate("trainerAvatar.audio===null && document.querySelector('#trainer-avatar').dataset.mouth==='closed'")
    evaluate("clearInterval(avatarWatch); speak('Cancel test',{force:true}); true")
    wait(evaluate, "speech.status==='playing' && trainerAvatar.openMouth")
    evaluate("cancelSpeech(); true")
    assert evaluate("trainerAvatar.audio===null && trainerAvatar.frame===null && !trainerAvatar.openMouth")
    print("Avatar check: waveform and cancellation passed", flush=True)

    # Avatar reactions come from training activity.
    evaluate("state.busy=true; syncTrainerAvatar(); true")
    assert evaluate("document.querySelector('#trainer-avatar').dataset.reaction==='thinking'")
    evaluate("state.busy=false; state.config.deepgram=true; live.enabled=true; live.paused=false; live.phase='listening'; updateLiveUI(); true")
    assert evaluate("document.querySelector('#trainer-avatar').dataset.reaction==='listening'")
    evaluate("live.stop(); document.querySelector('#answer-input').value='Test answer'; document.querySelector('#answer-form').requestSubmit(); true")
    wait(evaluate, "state.session.reviewing && !state.busy")
    assert evaluate("document.querySelector('#trainer-avatar').dataset.reaction==='supportive'")
    evaluate("state.session.attempts[0].mode='ai'; state.session.attempts[0].score=95; syncTrainerAvatar(); true")
    assert evaluate("document.querySelector('#trainer-avatar').dataset.reaction==='positive'")
    evaluate("openSettings('avatar'); true")
    wait(evaluate, "Boolean(document.querySelector('#trainer-voice'))")
    evaluate("""(() => {
        window.chooseAvatarCheckVoice = (value) => {
            const select = document.querySelector('#trainer-voice');
            select.value = value;
            select.dispatchEvent(new Event('change', {bubbles:true}));
        };
        chooseAvatarCheckVoice('male');
        return true;
    })()""")
    assert evaluate("document.querySelector('#avatar-visible').disabled && document.querySelector('#avatar-visible').checked")
    evaluate("document.querySelector('#settings-resume').click(); true")
    wait(evaluate, "document.querySelector('#trainer-avatar')?.hidden && !trainerAvatar.rig")
    evaluate("speak('Test male voice', {force:true}); true")
    wait(evaluate, "speech.status==='playing'")
    assert evaluate("!trainerAvatar.audio && document.querySelector('#trainer-avatar').hidden")
    evaluate("openSettings('avatar'); true")
    wait(evaluate, "Boolean(document.querySelector('#trainer-voice'))")
    evaluate("chooseAvatarCheckVoice('female'); document.querySelector('#settings-resume').click(); true")
    wait(evaluate, "document.querySelector('#trainer-avatar')?.hidden===false && trainerAvatar.rig?.canvas.dataset.ready==='true'")
    evaluate("openSettings('avatar'); true")
    wait(evaluate, "Boolean(document.querySelector('#avatar-visible'))")
    evaluate("document.querySelector('#avatar-visible').click(); document.querySelector('#settings-resume').click(); true")
    wait(evaluate, "Boolean(document.querySelector('#trainer-avatar'))")
    assert evaluate("document.querySelector('#trainer-avatar').hidden")
    assert evaluate("avatarCheckErrors.length===0"), evaluate("JSON.stringify(avatarCheckErrors)")
    evaluate("location.reload(); true")
    wait(evaluate, "Boolean(document.querySelector('#trainer-avatar')) && trainerAvatar.pack?.id==='marin'")
    assert evaluate("!trainerAvatar.enabled && document.querySelector('#trainer-avatar').hidden")
    print("Avatar check: reactions and persistence passed", flush=True)
    evaluate("window.avatarCheckErrors=[]; addEventListener('error', e=>avatarCheckErrors.push(e.message)); addEventListener('unhandledrejection', e=>avatarCheckErrors.push(String(e.reason))); true")
    evaluate("openSettings('avatar'); true")
    wait(evaluate, "Boolean(document.querySelector('#avatar-visible'))")
    evaluate("document.querySelector('#avatar-visible').click(); document.querySelector('#settings-resume').click(); true")
    wait(evaluate, "trainerAvatar.rig?.canvas.dataset.ready==='true'")
    assert evaluate("document.querySelectorAll('.trainer-portrait').length===1")
    evaluate("trainerAvatar.update('neutral','Test portrait'); trainerAvatar.rig.nextBlink=Infinity; true")
    if screenshot: screenshot()
    # Pose/clothing/hair outside the face must remain pixel-identical across emotions.
    assert evaluate("""(() => {
        const rig=trainerAvatar.rig; rig.mouth=0; rig.targetMouth=0; rig.nextBlink=Infinity; rig.blinkStart=null;
        rig.update('neutral',0); rig.displayedReaction='neutral'; rig.pendingReaction=null; rig.blinkStart=null; rig.paint(performance.now());
        const ctx=rig.canvas.getContext('2d'), width=rig.canvas.width, height=rig.canvas.height;
        const original=ctx.getImageData(0,0,width,height).data;
        for (const emotion of ['listening','thinking','positive','supportive']) {
            rig.update(emotion,0); rig.displayedReaction=emotion; rig.pendingReaction=null; rig.blinkStart=null; rig.paint(performance.now());
            const frame=ctx.getImageData(0,0,width,height).data;
            for(let y=0;y<height;y++) for(let x=0;x<width;x++) {
                if(y>=285 && y<=614 && x>=390 && x<=800) continue;
                const i=(y*width+x)*4;
                for(let c=0;c<4;c++) if(original[i+c]!==frame[i+c]) {
                    window.avatarInvariantDiff={emotion,x,y,c,before:original[i+c],after:frame[i+c]}; return false;
                }
            }
        }
        rig.update('neutral',0); rig.displayedReaction='neutral'; rig.pendingReaction=null; rig.blinkStart=null; rig.paint(performance.now()); return true;
    })()"""), evaluate("JSON.stringify(window.avatarInvariantDiff)")
    evaluate("""window.marinSnapshot=()=>{
        const rig=trainerAvatar.rig, canvas=document.createElement('canvas');
        canvas.width=rig.canvas.width; canvas.height=rig.canvas.height;
        const context=canvas.getContext('2d');
        context.drawImage(rig.images.base,0,0,canvas.width,canvas.height);
        context.drawImage(rig.canvas,0,0); return canvas.toDataURL('image/png');
    }; true""")
    for reaction in ("neutral", "listening", "thinking", "positive", "supportive"):
        encoded_frame = evaluate(f"trainerAvatar.rig.update('{reaction}',0); trainerAvatar.rig.displayedReaction='{reaction}'; trainerAvatar.rig.pendingReaction=null; trainerAvatar.rig.blinkStart=null; trainerAvatar.rig.paint(performance.now()); marinSnapshot()")
        (ROOT / f"logs/marin-render-{reaction}.png").write_bytes(base64.b64decode(encoded_frame.split(",", 1)[1]))
    if audio:
        evaluate("""(() => {
            state.config.tts={provider:'fish',ready:true}; const original=window.fetch;
            window.fetch=(input,options)=>String(input).includes('/api/speech')
                ? Promise.resolve(new Response(Uint8Array.from(atob('%s'), c=>c.charCodeAt(0)),{headers:{'Content-Type':'audio/mpeg'}}))
                : original(input,options);
            speak('MP3 streaming test',{force:true}); return true;
        })()""" % base64.b64encode(audio.read_bytes()).decode())
        wait(evaluate, "speech.status==='playing' && trainerAvatar.openMouth")
        assert evaluate("Boolean(speech.audio && speech.audio.src.startsWith('blob:'))")
        wait(evaluate, "trainerAvatar.rig.canvas.dataset.mouth==='open'")
        wait(evaluate, "trainerAvatar.rig.blinkStart===null && trainerAvatar.rig.displayedReaction===trainerAvatar.reaction")
        encoded_frame = evaluate("marinSnapshot()")
        (ROOT / "logs/marin-render-speaking.png").write_bytes(base64.b64decode(encoded_frame.split(",", 1)[1]))
        evaluate("cancelSpeech(); true")
    assert evaluate("avatarCheckErrors.length===0"), evaluate("JSON.stringify(avatarCheckErrors)")


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--desktop", action="store_true")
    parser.add_argument("--audio", type=Path); args = parser.parse_args()
    faulthandler.dump_traceback_later(85, exit=True)
    directory = ROOT / "logs/avatar-check"; directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=directory, ignore_cleanup_errors=True) as temporary:
        settings = Settings(data_dir=Path(temporary)/"data", deepgram_key="", openai_key="", openrouter_key="", model="",
                            embedding_model="", qdrant_url="", qdrant_key="", tts_provider="system", fish_key="")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0)); port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="warning"))
        with patch("app.storage.store.load_cards", return_value=load_cards()[:3]):
            thread = threading.Thread(target=server.run, daemon=True); thread.start()
            for _ in range(100):
                if server.started: break
                time.sleep(.05)
            assert server.started
            url = f"http://127.0.0.1:{port}"
            try:
                if args.desktop:
                    from app.desktop.window import open_window
                    errors=[]; started=False
                    def check(window):
                        nonlocal started
                        if started: return
                        started=True
                        try: checks(window.evaluate_js, args.audio)
                        except Exception as error: errors.append(repr(error))
                        finally: window.destroy()
                    open_window(SimpleNamespace(url=url), on_loaded=check, profile_path=Path(temporary)/"profile")
                    assert started and not errors, errors
                else:
                    from playwright.sync_api import sync_playwright
                    with sync_playwright() as playwright:
                        browser=playwright.chromium.launch(channel="msedge",headless=True,args=["--autoplay-policy=no-user-gesture-required"])
                        page=browser.new_page(); page.goto(url)
                        checks(page.evaluate, args.audio, lambda: page.screenshot(path=str(ROOT/"logs/preview-avatar.png"),full_page=True))
                        page.set_viewport_size({"width":390,"height":844})
                        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                        assert page.locator("#trainer-avatar").is_visible()
                        page.screenshot(path=str(ROOT/"logs/preview-avatar-mobile.png"),full_page=True)
                        browser.close()
            finally:
                server.should_exit=True; thread.join(timeout=10)
    faulthandler.cancel_dump_traceback_later()
    print(json.dumps({"result":"passed","renderer":"WebView2" if args.desktop else "Edge", "checks":[
        "built-in avatar settings", "audio-driven open and closed mouth at low volume", "stop closes mouth",
        "thinking/listening/positive/supportive reactions", "male voice hides avatar", "visibility persistence",
        "Marin portrait layers", "invariant clothing and pose", "no JS errors"]}))


if __name__ == "__main__": main()
