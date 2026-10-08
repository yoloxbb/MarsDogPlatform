"""Try one presegmented WAV through real CPU ASR and installed simulated robot flow."""
import argparse
from model_assets import default_manifest
from pathlib import Path
import wave
from runtime_environment import ROOT


def validate_wav(path):
    path = path.expanduser().resolve(strict=True)
    if not path.is_file() or path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError("WAV must be a regular file below 20 MiB")
    with wave.open(str(path), "rb") as stream:
        if stream.getcomptype() != "NONE" or stream.getsampwidth() != 2 or stream.getnchannels() != 1:
            raise ValueError("Use mono 16-bit PCM WAV")
        rate, frames = stream.getframerate(), stream.getnframes()
        if rate != 16000 or not 0 < frames <= 16000 * 60:
            raise ValueError("Use 16 kHz WAV of at most 60 seconds")
        if len(stream.readframes(frames)) != frames * 2:
            raise ValueError("WAV data is truncated")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wav", required=True, type=Path)
    parser.add_argument("--expect-event")
    parser.add_argument("--expect-outcome", choices=("success", "action_failed_or_canceled",
                                                   "rejected_before_goal", "no_dispatch_requested"))
    parser.add_argument("--terminal-timeout", type=float, default=75)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--voice-manifest", type=Path, default=None)
    parser.add_argument("--intent-manifest", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=ROOT / "out/recording-trial")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        wav = validate_wav(args.wav)
    except (ValueError, OSError, wave.Error) as error:
        parser.error(str(error))
    if not 1 <= args.terminal_timeout <= 180:
        parser.error("terminal-timeout must be 1..180 seconds")
    if args.check_only:
        print("WAV format ready: " + str(wav))
        return 0
    from check_voice_cpu_ros import main as run
    args.voice_manifest = args.voice_manifest or default_manifest("voice")
    args.intent_manifest = args.intent_manifest or default_manifest("intent")
    # Strict here means explicit user expectations must match; it does not
    # certify model accuracy or require unverified motions to be enabled.
    return run(["--with-behavior", "--acceptance", "strict", "--timeout", str(args.timeout),
                "--voice-manifest", str(args.voice_manifest), "--intent-manifest", str(args.intent_manifest),
                "--output", str(args.output)],
               trial={"wav": str(wav), "expect_event": args.expect_event,
                      "expect_outcome": args.expect_outcome, "terminal_timeout": args.terminal_timeout})


if __name__ == "__main__":
    raise SystemExit(main())
