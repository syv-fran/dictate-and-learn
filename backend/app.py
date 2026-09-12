
import warnings

warnings.filterwarnings(
    "ignore", 
    category=UserWarning, 
    message=r"(?s).*torchcodec is not installed correctly.*"
)

# Alternative: Ignore all UserWarnings coming from the specific pyannote module path
warnings.filterwarnings(
    "ignore", 
    category=UserWarning, 
    module="pyannote.audio.core.io"
)
import csv
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

import huggingface_hub  # needed for exception handling
import numpy as np
import torch
import whisperx
from flask import Flask, abort, jsonify, request, send_file, send_from_directory
from flask_cors import CORS
from piper import PiperVoice as TTSVoice  # currently using Piper as TTS, could change.
from werkzeug.utils import secure_filename

from . import progresslog, speechfunc, tts, words


@dataclass()
class Analysis:
    tensor_audio: torch.Tensor
    tensor_emissions: torch.Tensor
    tensor_start: float
    tensor_end: float
    tensor_use_retry: bool 
    
@dataclass()
class RecogState: #this is the state of the current recognition task, shared between threads.
#we assume single-user, controlled by the most recent session, so models can persist.
    analysis: Analysis | None = None
    audio: np.ndarray | None = None
    lang:str = ""
    model = None
    model_name: str | None = None
    retry_audio: np.ndarray | None  = None
    selected_lang: str = ""
    sentence_idx: list[int] | None = None
    voice: TTSVoice | None = None
    voice_lang: str = ""
    words: list[dict] | None = None
    word_align_model = None
    word_align_meta: dict | None = None
    word_align_lang: str | None = None
   
    recognition_is_ready: threading.Event = field(default_factory=threading.Event)

@dataclass()
class GlobalState: 
    # - global locks for functions which aren't thread-safe
    # - anything constant, but loaded lazily.
    voice_lock: threading.Lock = field(default_factory=threading.Lock)
    phone_aligner: speechfunc.PhoneAligner | None = None
    phone_align_lock: threading.Lock = field(default_factory=threading.Lock)

# instantiate the app, for decorators:
app = Flask(__name__)
app.config.from_object(__name__)

def get_env_bool(key: str, default: bool = False) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    return value.lower() in ("true", "1", "on", "yes", "enabled")

def get_form_bool(field_name: str, default: bool) -> bool:
    value = request.form.get(field_name)
    if value is None:
        return default
    return value.lower() in ("true", "1", "on", "yes", "enabled")

# Two-stage speech recognition process using whisperx and potentially saved state
def recognize(audio_filename: str, selected_lang: str, model_name: str, was_preset:bool = False):
    try:
        if model_name == state.model_name and state.model is not None:
            logger.info("using existing model")
            model=state.model
        else:        
            model_name = secure_filename(model_name) # sadly prevents us passing custom model.
            logger.info("Loading %s", model_name)
            state.model = model = whisperx.load_model(
                model_name,
                device=accel_device,
                compute_type="default",
                download_root=model_dir,
                language=selected_lang if selected_lang else None,
                local_files_only=local_files_only,
            )     
            logger.info("Loaded %s", model_name)
            state.model_name = model_name

        state.selected_lang = selected_lang
        state.audio = audio = whisperx.load_audio(audio_filename)

        logger.info("About to transcribe with %s %s", model_name,selected_lang)
        initial_result = model.transcribe(audio, language=selected_lang,task='transcribe') 
        # before alignment
        state.lang = lang = initial_result["language"]
        if not selected_lang:
            logger.info("Language: %s", lang) # todo: display parsed language id at top of wordlist?
        logger.info("Text: %s ...", words.prettify_head(initial_result))
        r=words.make_partial_resultlist(initial_result['segments'])
        if not was_preset:
            signal_server_results(r, lang, is_partial=True)

        if state.word_align_model is not None and state.word_align_lang == lang:
            logger.debug("Using existing word alignment model")
        else:
            logger.info("Loading alignment model")
            state.word_align_model, state.word_align_meta = whisperx.load_align_model(
                language_code=lang,
                model_name=custom_alignment_model_name,
                model_dir=model_dir,
                device=accel_device,
                model_cache_only=local_files_only,
            )
            state.word_align_lang = lang

        logger.info("Preparing to align words.")
        whisper_result = whisperx.align(
            initial_result["segments"],
            state.word_align_model,
            state.word_align_meta,
            audio,
            accel_device,
            return_char_alignments=False,
        )
        state.sentence_idx, state.words = words.make_words_list(whisper_result["segments"])
        words.mark_unlikely(state.words)
        print(state.words)
        return state.words, lang
    except huggingface_hub.errors.LocalEntryNotFoundError:
            logger.error(
                "ERROR: Cannot load speech model %s locally. Download it separately, or unset variable LOCAL_FILES_ONLY to try to get it on demand. ",
                model_name,
            )
    except (
            huggingface_hub.errors.EntryNotFoundError,
            huggingface_hub.errors.RepositoryNotFoundError,
            OSError,
            RuntimeError,
            ValueError,
        ) as e:
            logger.error("ERROR: Speech model - %s", e)
    return [],''

# phone_aligner is the phoneme speech model. It is a constant, but loaded on demand.
# we lock inside this fn so we don't try to load when mid-load.
# TODO: try/except for fatal error for no phone aligner?
def ensure_phone_aligner() -> speechfunc.PhoneAligner:
    with global_state.phone_align_lock:
        if global_state.phone_aligner is None:
            global_state.phone_aligner = speechfunc.load_phone_aligner(
                model_dir, local_files_only, accel_device
            )
    return global_state.phone_aligner

# ensure the current recognition state has a loaded voice model in the correct lang.
# we lock outside this- as well as not nesting voice loading, must ensure voice_lang is still current
def ensure_matching_voice() -> TTSVoice | None: 
    if not state.voice or state.voice_lang != state.lang:
        state.voice = tts.voice_model(state.lang, model_dir,local_files_only)
        state.voice_lang = state.lang
        return state.voice # None is a last resort if impossible.

# Run a phoneme model over stored audio, between start and end, unless we've already got it
def emissions_using_state(start: float, end: float,use_retry:bool) ->torch.Tensor:

    if ( state.analysis is not None
        and state.analysis.tensor_start == start
        and state.analysis.tensor_end == end
        and state.analysis.tensor_use_retry == use_retry
    ): 
        return state.analysis.tensor_emissions

    global_state.phone_aligner=ensure_phone_aligner()
  
    if (use_retry):
        audio = state.retry_audio
    else :
        audio = state.audio
    if audio is None:
        logger.error("ERROR No audio available for phoneme analysis")
        return torch.empty(0)
    tensor_audio,  tensor_emissions = (
        speechfunc.process_phone_audio(
            audio, global_state.phone_aligner, start, end)
        )   
    state.analysis = Analysis(
        tensor_emissions=tensor_emissions, 
        tensor_audio=tensor_audio, 
        tensor_start=start, 
        tensor_end=end, 
        tensor_use_retry=use_retry)     
    return tensor_emissions

# Tell the client that there is data available, store data thread-safely.
def signal_server_results( wordlist:list[dict], lang:str, is_partial:bool):    
    global recog_result
    recog_result = {"is_partial": is_partial, "words": wordlist, "lang": lang}
    logger.critical("PARTIAL" if is_partial else "READY")    

#Do recognition of audio file, signal results, then continue to prep for future work
def blocking_recognition_task(filename:str, selected_lang:str, model, was_preset=False):

    wordlist, lang = recognize(filename, selected_lang, model, was_preset) # time-consuming
    state.recognition_is_ready.set()
    signal_server_results(wordlist, lang,is_partial=False)

    # now load models in advance for next stage.
    global_state.phone_aligner=ensure_phone_aligner()
    # ..  But not if we're still using a different voice, already loading, or super busy.
    if global_state.voice_lock.acquire(timeout=1):
        try:
            ensure_matching_voice()
        finally:
            global_state.voice_lock.release()
        

def to_list(x:dict): #for each phoneme, record its text, score and length
    return [x["text"], round(x["score"] * 5,3), x["end"] - x["start"]]


@app.route("/start_recog", methods=["POST"])
def start_recog_task():
    lang = request.form.get("lang")
    model = request.form.get("model","tiny")
    state.recognition_is_ready = threading.Event()

    #This sadly prevents us passing custom model paths.
    # but no need to do further checks: empty string will fail.
    model = secure_filename(model) 
    if "audio" in request.files:  # if client provided audio file, write it as file on server.
        audio = request.files["audio"]
        logger.info("Incoming audio, format: %s", format(audio))
        try:
            audio.save("audio.wav")  # which we save as a temporary file
        except OSError as e:
            logger.error("ERROR: Cannot write to server directory: %s", e)
            return {"error": e.strerror}, 500
        filename = "audio.wav"
        using_preset=False
    else:  # or client requests static audio file from this server, typically default preset.
        using_preset=True
        filename = os.path.join(
            app.static_folder or 'static', secure_filename(request.form.get("serverfile", "preset.mp3"))
        )
        if not lang:
           state.lang = lang = "pt"
        logger.info("Using preset text.")
        # although we haven't finished, preset has enough info for READY because 
        # it contains timing data, hence is_partial==False
        signal_server_results(words.wordlist, lang,is_partial=False)

    logger.info("Starting recognition with model: %s, %s", model, filename)

    task_thread = threading.Thread(
        target=blocking_recognition_task,
        kwargs={
            "filename": filename,
            "selected_lang": lang,
            "model": model,
            "was_preset": using_preset
        },
    )
    task_thread.start()
    return {}, 202


@app.route("/robot", methods=["GET"])
def robot():
    phones = request.args.get("phones")

    if not phones:
        return {"error": "no phones"}, 404
    logger.info("Synthesizing speech.. %s", phones)

    with global_state.voice_lock:
        ensure_matching_voice()
        if state.voice is None:
            return {"error": "No voice model"}, 404
        audio_buf = tts.synthesize(phones,state.voice)
    
    return send_file(audio_buf,mimetype="audio/wav", as_attachment=False, download_name="robot_o.wav")


@app.route("/progress")
def stream_logs():
    iterable = progresslog.make_queue(logger)()
    response = app.response_class(iterable, mimetype='text/event-stream')
    response.headers["X-Accel-Buffering"] = "no"
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.route("/get_recog")
def get_recog():
    #logger.info("Requested result:%s", recog_result) 
    if not recog_result:
        # it's gone wrong so don't wait()
        return {"error": "Processing incomplete"}, 404
    return recog_result

@app.route("/retry", methods=['POST']) # API call
def retry_segment():
    is_sentence=get_form_bool("is_sentence",True)
    orig_seg_start = float(request.form.get("orig_seg_start",0.0))
    orig_seg_end = float(request.form.get("orig_seg_end",0.0))
    sent = int(request.form.get("sent",-1))
    prefix =  request.form.get("prefix")
    suffix =  request.form.get("suffix")
    audio_in = request.files["audio"]

    if not audio_in:
         abort(400,description="Audio not provided for retry")
    try:
        filename = "retry_audio.wav"
        audio_in.save(filename)  # which we save as a temporary file
        audio_in_array = whisperx.load_audio(filename)
    except OSError as error:
        abort(500,description="IO error at retry:"+(error.strerror or ""))
    if not state.sentence_idx or not state.words or not state.audio or not state.model:
        abort(500,description="Incomplete state to retry")
    if sent<0 or sent>len(state.sentence_idx): 
        abort(400,description="Invalid sentence number to retry")
    global_state.phone_aligner=ensure_phone_aligner()

    sent_start, sent_end = words.get_sent_bounds(
            sent, state.sentence_idx, state.words
    ) 
    print(f" {sent_start=} {sent_end=} {orig_seg_start=} {orig_seg_end=} ")   

    audio, size_received = speechfunc.construct_retry_audio(
        audio_in_array,is_sentence,
        sent_start,sent_end,orig_seg_start,orig_seg_end,
        state.audio,global_state.phone_aligner.frame_duration)
    print(f" {size_received=} ")

    state.retry_audio=audio
    initial_result=state.model.transcribe(audio, language=state.lang,task='transcribe')
    whisper_result = whisperx.align(
            initial_result["segments"], 
            state.word_align_model,
            state.word_align_meta,
            audio,
            accel_device,
            return_char_alignments=False,
        )
    _,result=words.make_words_list(whisper_result['segments'])
    if not result:
        #could: abort(404,description="No speech recognition result") 
        return jsonify({'text':[],'start':0,'end':size_received}) 
    if is_sentence and prefix and suffix:
        first,last=words.split_by_fuzzy_match(result,prefix,suffix)
    else:
        first = orig_seg_start - sent_start
        last = orig_seg_start - sent_start + size_received

    best_text, first,last =words.chop_text_from_words(
            whisper_result['segments'],first,last)
   
    return jsonify({'text':best_text,'start':first,'end':last})

@app.route("/analyze", methods=["GET"]) # API call
def letter_list():

    sent_start = sent_end = 0.0  # only for beam search
    text = request.args.get("text")  # optional: if not text, we calc raw result.
    sent = request.args.get("sent",'-1') # optional: if invalid, we use retry data instead
    start = request.args.get("start")
    end = request.args.get("end")
    beam = request.args.get("beam") # experimental option  

    state.recognition_is_ready.wait()  # await recognition structures (could have been a preset)
    if (start is None or end is None or sent is None
            or not state.sentence_idx or not state.words):
        abort (400,description="Incomplete data for segment analysis")

    start = float(start)
    end = float(end)
    sent = int(sent)
    use_retry:bool = sent<0 or sent>= len(state.sentence_idx)

    global_state.phone_aligner=ensure_phone_aligner()
    
    if beam: #experimental
        assert not use_retry
        sent_start, sent_end = words.get_sent_bounds(
                   sent, state.sentence_idx, state.words
               )      
        emissions = emissions_using_state(sent_start, sent_end,False)
    # first, run phoneme model if we haven't already done so
    else:
        emissions = emissions_using_state(start, end,use_retry)

    if emissions.shape[0]==0:
        abort(404,description="Speech recognition failed at analysis stage")
    if beam:
        result, phones = speechfunc.raw_recog_beam(
            sent_start, global_state.phone_aligner, emissions
        )
    elif not text or not text[0]:
        result, phones = speechfunc.raw_recog(
            start, global_state.phone_aligner, emissions
        )
    else:
        if request.args.get("useprefixes"):
            prefix = request.args.get("prefix","")
            suffix = request.args.get("suffix","")
        else:               
            prefix, suffix = words.build_context(
                state.sentence_idx[int(sent)], state.words, start, end
            )
        phones = words.phonemize_words([prefix, text, suffix], state.lang)
        result = speechfunc.phone_align(
            start, phones, global_state.phone_aligner, emissions
        )
    print(result)

    num_list = list(map(to_list, result))
    return jsonify( #previously prefix and suffix.
        {"list": num_list, "phones": phones}
    )

@app.route("/phoneme_info", methods=["GET"])
def get_phoneme_info():
    base_dir = Path(__file__).resolve().parent # directory containing this code
    with open( base_dir / "ipa.tsv", mode="r") as infile:
        reader = csv.reader(infile, delimiter="\t")
        tsv = {rows[0]: [rows[1], rows[2], rows[3]] for rows in reader}
    return jsonify(tsv)

@app.route("/")
@app.route("/static/")
def serve_index():
    return send_from_directory(app.static_folder or "static", "index.html")

@app.route("/<path:path>")
def serve_assets(path):
    return send_from_directory(app.static_folder or "static", path)

# Set up custom webserver logging which sends progress/errors to client. 
# Include logs from speech subsystems.
logger = progresslog.start("DAL")

# set up global variables for thread management
state = RecogState()
recog_result = {}

global_state = GlobalState()

# Set LOCAL_FILES_ONLY=true if app is not allowed to download models. 
# Similar behaviour to combo of "HF_HUB_OFFLINE" = "1"  and "TRANSFORMERS_OFFLINE" = "1"
local_files_only = get_env_bool("LOCAL_FILES_ONLY", default=False) 

# for additional language support, see https://github.com/m-bain/whisperX/blob/main/whisperx/alignment.py
# and pass the model name in ALIGN_MODEL  (whisperx uses the command-line argument --align_model)
custom_alignment_model_name = os.getenv("ALIGN_MODEL", None)

#Set MODEL_DIR to the storage location for speech models.
#The default model store location is $HOME/datasets (or ./datasets if there is no home directory)
model_dir = os.getenv(
    "MODEL_DIR",
    os.path.join(os.getenv("HOME", os.getcwd()), "datasets"),
)
#Set TORCH_DEVICE to "cuda" or "mps" to use GPU acceleration, otherwise CPU is used.
accel_device = os.getenv('TORCH_DEVICE',"cpu") 

#Set DAL_DEV to enable CORS for development build: 5173 is a dev Vite server for the js
if get_env_bool('DAL_DEV', default=True):
    CORS(
        app,
        origins=["http://localhost:5173"],
        expose_headers=["Access-Control-Allow-Origin"],
    )
if __name__ == "__main__":
    app.run(debug=get_env_bool('DAL_DEV'), threaded=True) 
