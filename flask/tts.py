import io
import logging
import wave
from pathlib import Path
from urllib.parse import quote

import requests
from piper import PiperVoice, SynthesisConfig
from piper.download_voices import VOICES_JSON, download_voice


def synthesize(phones: str, voice:PiperVoice):
    audio_buffer = io.BytesIO()
    with wave.open(audio_buffer, "wb") as wav_file:
        syn_config = SynthesisConfig(length_scale=2)
        voice.synthesize_wav("[[" + phones + "]]", wav_file, syn_config)
    audio_buffer.seek(0)
    return audio_buffer


def download_piper_voice(voice_name: str, voice_dir: Path):
    logger = logging.getLogger("DAL")
    try:
        download_voice(voice_name, voice_dir)
        return
    except UnicodeEncodeError:
        safe_voice_name = quote(voice_name, safe="")
        logger.warning(
            "Voice name %s contains non-ASCII characters; retrying with URL-encoded name %s.",
            voice_name,
            safe_voice_name,
        )
        download_voice(safe_voice_name, voice_dir)


def voice_model(lang: str, model_dir: str,local_files_only:bool):

    logger=logging.getLogger("DAL")
    voice = None
    voice_dir: Path = Path(model_dir) / "piper-voices"
    voice_dir.mkdir(exist_ok=True)
    voice_name = pick_voice(lang, voice_dir.glob("*.onnx"))
    #logger.info("Voices installed: %s", list(voice_dir.glob("*.onnx")))
    if not voice_name:
        logger.info("No text to speech voices found locally for language %s", lang)
        if not local_files_only:
            voice_list = get_piper_online_voices()
            voice_name = pick_voice(lang, voice_list)         
            if voice_name:
                voice_name = quote(voice_name, safe="") # results of get_piper_online.. may contain non ASCII
                logger.info("Downloading Piper voice model %s.",voice_name)
                download_voice(voice_name,voice_dir)
                voice_name = f"{voice_name}.onnx"
    if voice_name:
        logger.info("Loading synthesis model for voice: %s", voice_name)
        voice = PiperVoice.load(voice_dir / voice_name)

    if voice:
        logger.info("Loaded synthesis model")
    else:
        logger.info("Piper voice not found for lang %s", lang)
    return voice


def get_piper_online_voices ():
    try:
        response=requests.get(VOICES_JSON, timeout=10)    
        response.raise_for_status() 
        return response.json()
    except requests.exceptions as e:
        logger=logging.getLogger("DAL")
        logger.error("Could not find Piper model locally, and could not download list of Piper models: %e.",e.strerror or "Error")
        return []

def pick_voice (lang, voice_list):
    matching_voices = [
             f for f in voice_list if str(f.name).startswith(lang)       
        ]
    if not matching_voices:
         return None
    return matching_voices[0]
 