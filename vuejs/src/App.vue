<script setup>
import { ref, nextTick} from 'vue'
import { findIconDefinition } from '@fortawesome/fontawesome-svg-core';

//can change these, eg 'http://192.168.5.111:5000';
const APIHOST= import.meta.env.VITE_APP_HOSTNAME || 'http://localhost:5000';
const PRESETFILE = "preset.mp3" 

const mainRecorder = ref({ 
  isAudioAvail: false, // convenience booleans for UI
  isRecordingNow: false, 
  isRecordingPaused: false,
  audioChunks: [],
  mediaRecorder: null,
  element: "RecAudioPlayer", //TODO: work out init function. set up element link directly? same with rawID.Aud..
  blob: null,
});

const reRecorder = ref({
  isAudioAvail: false, //TODO: after init fn, could make a fn examining src link of element to find out this.
  isRecordingNow: false, //TODO: investigate status of mediaRecorder instead?
  isRecordingPaused: false, //TODO: ditto.
  audioChunks: [],
  mediaRecorder: null,
  element: "ReRecAudioPlayer",
  blob: null,
});

const messages = ref([]);
const wordsList = ref([]);
const currentSeg = ref({ text: "", start: 0, end: 0, audio: null, more: false, isRetry: false })
const correctText = ref("");

const pho = ref({ active: -1, nButtons: 0, info: "", text: "", list: [], playerID: "phoID.AudioPlayer" })
const corr = ref({ active: -1, nButtons: 0, info: "", text: "", list: [], playerID: "corrID.AudioPlayer" })
const raw = ref({ active: -1, nButtons: 0, info: "", text: "", list: [], playerID: "rawID.AudioPlayer" })
const prefix = ref(''); // current sentence prefix+suff, calculated here with corrections, for use with rerecord.
const suffix = ref(''); // could move into currentSeg structure, though we don't need to update it until analyze/rerecord.
const onlyPartialWords = ref(false);
const isAnalyzing = ref(false);
const isRecognizing = ref(false);
const checked = ref(false); // just for testing.
const radioFullSentence = ref(false); // status of radio buttons

const scrollContainer = ref(null); // vue language feature: initialises to element with ref scrollContainer
const RecAudioPlayer = ref(null); // ditto
const segAudioPlayer = ref(null); // ditto
const ReRecAudioPlayer = ref(null); // ditto


let currentSent = -1;
let infoDictionary = null;
let _langReturned = null;
let progressSource = null;

function playAudioInside(event) {
  try {
    const children = event.currentTarget.getElementsByTagName("AUDIO");
    children[0].play();
    addMessage("playing from " + children[0].currentTime);
  } catch (error) { addMessage('cannot play..' + error.message + " at " + event.target.id) }
}

function initDynamicClip(audioData) {
  if (currentSeg.value.audio != null) { return; } //only call once
  audioData.addEventListener('timeupdate', () => {
    if (audioData.currentTime >= currentSeg.value.end) {
      audioData.pause();
      audioData.currentTime = currentSeg.value.start;
    }
  });
}

function linkSynthAudio(phones, location) {
  const audioData = document.getElementById(location);
  audioData.preload = 'none';
  audioData.src = `${APIHOST}/robot?phones=${encodeURIComponent(phones)}`;
  audioData.controls = false;
}

function soundPause(recorder) {
  recorder.isRecordingPaused = true;
  recorder.isRecordingNow = false;
  recorder.mediaRecorder.pause();
}

function soundStop(recorder) {
  //TODO: fix this!
//  if (recorder.mediaRecorder.stream) {
//    stream.getTracks().forEach(track => track.stop()); // just to kill browser icon
//  }
  recorder.isRecordingPaused = false;
  recorder.isRecordingNow = false;
  recorder.isAudioAvail = true;
  recorder.mediaRecorder.stop();
}

async function soundRecord(recorder) {
  if (recorder.isRecordingPaused) {
    recorder.isRecordingPaused = false;
    recorder.isRecordingNow = true;
    recorder.mediaRecorder.resume();
    return;
  }
  if (recorder.isAudioAvail) {
    const ok = confirm("Clear existing recording?");
    if (!ok) { return; }
    clearAudio(recorder);
  }
  if (!window.isSecureContext) {
    addMessage("Recording function cannot run: insecure context.");
    return;
  }
  recorder.isRecordingNow = true;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    let options = { mimeType: 'audio/webm' };

    if (!MediaRecorder.isTypeSupported('audio/webm')) {
      options = { mimeType: 'audio/mp4' };
    }
    recorder.mediaRecorder = new MediaRecorder(stream,options);
    recorder.mediaRecorder.addEventListener('dataavailable', event => {
      if (!event.data || event.data.size === 0) {
        return;
      }
      recorder.audioChunks.push(event.data);
    });
    recorder.mediaRecorder.addEventListener('stop', () => {
      // could use stream directly, but downstream need to seek, which streams can't
      recorder.blob = new Blob(recorder.audioChunks);
      recorder.audioChunks = [];
      const e = document.getElementById(recorder.element);
      e.src = URL.createObjectURL(recorder.blob);
      //TODO: is turning controls on/off even necessary? we switch display on off
      if (recorder == mainRecorder.value) { e.controls = true; }
    });
    recorder.mediaRecorder.start();
  } catch (error) {
    recorder.isRecordingNow = false;
    addMessage(error.message)
  };
}

function clearAudio(recorder) {
  const a = document.getElementById(recorder.element);
  if (a) {
    URL.revokeObjectURL(a.src);
    if (segAudioPlayer.value.src==a.src) {
      segAudioPlayer.value.removeAttribute('src');
    } // segAudioPlayer could have been attached to either recorder.
    a.removeAttribute('src');
  }
  recorder.isAudioAvail = false;
  recorder.isRecordingPaused = false;
  recorder.blob = null;
  recorder.audioChunks = [];
  if (recorder.mediaRecorder) {
    soundStop(recorder);
    recorder.mediaRecorder = null;
  }
}

function wordListReset() {
  wordsList.value.forEach(item => {
    item.active = false;
    item.disabled = false;
  });
  currentSeg.value.text = "";
}

function addMessage(data) {
  if (messages.value.length > 20) {
    messages.value.shift();
  }
  messages.value.push(data);
  nextTick(() => {
    scrollContainer.value.scrollTop = scrollContainer.value.scrollHeight;
  });
}

function AwaitLogInit() {
  return new Promise((resolve, reject) => {
    progressSource = new EventSource(`${APIHOST}/progress`);
    let isFirstMessage = true;
    progressSource.onmessage = async function (event) {
      addMessage(event.data);
      if (isFirstMessage) {
        isFirstMessage = false;
        resolve();
      }
      if (event.data.includes("READY") || event.data.includes("PARTIAL")) {
        try {
          const resp = await fetch(`${APIHOST}/get_recog`);
          if (!resp.ok) {throw new Error(`Recognition failure: ${resp.status} ${resp.statusText}`);}
          const result = await resp.json();
          onlyPartialWords.value = result.is_partial;
          if (!result.is_partial) {isRecognizing.value=false;}
          makeWordList(result);
        } catch (error) {
          addMessage(error.message);
        }
      }
    };
    progressSource.onerror = () => {
      addMessage(`Log error - is server ${APIHOST} running?`);
      reject(new Error("Connection to server logger failed"));
    };
  }
  );
}

async function doRecog() {
  //top level function so catch errors here 
  try {
    //ensure text messages are arriving at log file before we ask to do recognition (avoid race)
    if (progressSource == null || progressSource.readyState === EventSource.CLOSED) {
      await AwaitLogInit();
    }
    isRecognizing.value = true;
    const formData = new FormData();
    formData.append("lang", document.getElementById('langselect').value);
    formData.append("model", document.getElementById('modelselect').value);
    if (mainRecorder.value.blob == null) {
      formData.append("serverfile", PRESETFILE);
    }
    else {
      formData.append("audio", mainRecorder.value.blob, 'audio.wav');
    }
    const r = await fetch(`${APIHOST}/start_recog`, {
      method: 'POST',
      body: formData
    });
    if (!r.ok) { throw new Error(`${r.status} ${r.statusText}`); }
  } catch (error) { addMessage(`Error submitting recognition: ${error.message}`) }
}

async function makePreset() {
  try {
    const e = document.getElementById(mainRecorder.value.element);
  
  clearAudio(mainRecorder.value);
  //TODO: if there is Audio that is not a Preset, ask for permission first.


  e.src = `${APIHOST}/static/${PRESETFILE}`;
  e.preload='metadata';
  mainRecorder.value.controls = true;
  mainRecorder.value.isAudioAvail = true;
  await doRecog();
  } catch (error) { addMessage("error with preset:" + error.message) }
}
 

function makeWordList(result) {
  // if result has the same text as before (old could have been partial result) just update with new info.
  // otherwise, make new list, unselected hence currentSeg will be the empty segment.
  if (wordsList.value.length == result.words.length && 
      wordsList.value.every((item, index) => item.text == result.words[index].text)) {
        wordsList.value.forEach((item,idx,array) => {
          array[idx].sent = result.words[idx].sent;
          array[idx].start=result.words[idx].start || 0;
          array[idx].end=result.words[idx].end || 0;
          array[idx].unlikely=result.words[idx].unlikely || 0;
        });  
        addMessage("Merging word lists")       
      } 
  else {
  wordsList.value = result.words.map(obj => ({
    text: obj.word,
    sent: obj.sent,
    start: obj.start || 0,
    end: obj.end || 0,
    unlikely: obj.unlikely || 0,
    id: 'w' + obj.idx,
    active: 0,
    disabled: 0,
    correction: '',
  }));
  }
  segAudioPlayer.value.src = RecAudioPlayer.value.src; // js passes strings by VALUE, don't forget!
  initDynamicClip(segAudioPlayer.value); //TODO: investigate init methods, remove this call.
  updateSeg();
  currentSeg.value.audio = segAudioPlayer.value;
  _langReturned = result.lang;
}

function toggleAndUpdateSeg(word) {
  if (word.disabled) { return; }
  word.active = !word.active;
  updateSeg();
}

// updateSeg(): calculate currentSeg structure, containing a span of the first word that
// the user has selected, and subsequent selected words if contiguous and in same sentence.
// ie if wordsList is A b c. D e and user selects b c. D, the segment text is "b c."
function updateSeg() { 
  let x = 0;
  let done = false;
  const oldSeg = currentSeg.value.text;

  currentSent = -1;
  currentSeg.value.text = "";
  currentSeg.value.start = -1;
  currentSeg.value.end = 0;
  currentSeg.value.more = false;
  for (x = 0; x < wordsList.value.length; ++x) {
    if (wordsList.value[x].active && !done && (currentSent == -1 || wordsList.value[x].sent == currentSent)) {
      currentSeg.value.text += wordsList.value[x].text + ' ';
      if (currentSeg.value.start == -1) {
        currentSeg.value.start = wordsList.value[x].start;
      }
      currentSeg.value.end = wordsList.value[x].end;
      currentSent = wordsList.value[x].sent;
    }
    else if (currentSent != -1) {
      done = true;
      if (currentSeg.value.text != "" && wordsList.value[x].active) {
        currentSeg.value.more = true;
        break;
      }
    }
  }
  if (onlyPartialWords.value) { currentSeg.value.text += " (not ready yet)"; }
  segAudioPlayer.value.src = RecAudioPlayer.value.src;
  segAudioPlayer.value.currentTime = currentSeg.value.start;
  currentSeg.value.audio = segAudioPlayer.value;

  if (currentSeg.value.text != oldSeg) {
    correctText.value = ''; // wipe correction box if user's choice has changed.
  }
  //  addMessage(" seq =*" + currentSeg.value.text + currentSeg.value.start + " to " + currentSeg.value.end + '*');
}

function wordListToClipboard() { // TODO: could we do with reduce or an accumulator???
  //top level: catch errors
  try {
    let text = '';
    for (let x = 0; x < wordsList.value.length; ++x) {
      text += printable(wordsList.value[x]);
    }
    navigator.clipboard.writeText(text);
  }
  catch (error) { addMessage("clipboard error:" + error.message); }
}

function printable(word) {
  if (word.disabled) {
    if (word.correction != '') {
      return word.correction + ' ';
    }
    return '';
  }
  else {
    return word.text + ' ';
  }
}

function wordsAtEnd(end, sent) {
  let text = '';
  for (let x = 0; x < wordsList.value.length; ++x) {
    if (wordsList.value[x].sent > sent) {
      break;
    }
    if (wordsList.value[x].start >= end) {
      text += printable(wordsList.value[x]);
    }
  }
  return text;
}

function wordsBeforeStart(start, sent) {
  let text = ''
  for (let x = 0; x < wordsList.value.length; ++x) {
    if (wordsList.value[x].sent > sent) {
      break;
    }
    if (wordsList.value[x].end <= start && wordsList.value[x].sent == sent) {
      text += printable(wordsList.value[x]);
    }
  }
  return text;
}

function correctWordsList() { // add user's correction to word list
  let doneWork = false;
  let x = 0;
  if (correctText.value != '') {
    for (x = 0; x < wordsList.value.length; ++x) {
      if (wordsList.value[x].start >= currentSeg.value.start &&
        wordsList.value[x].end <= currentSeg.value.end) {
        wordsList.value[x].active = false;
        wordsList.value[x].disabled = true;
        if (!doneWork) {
          wordsList.value[x].correction = correctText.value;
          doneWork = true;
        }
        else
          wordsList.value[x].correction = '';
      }
    }
  }
  correctText.value = '';
  updateSeg();
}

function mapBricks(letter, i) {
  const l = [];
  let n = 0
  for (n = 5; n > 0; --n) {
    if (letter[1] > n) {
      l.push("brickfill");
    }
    else {
      l.push("brickempty")
    }
  }
  return {
    text: letter[0],
    id: `${letter[0]}-${i}`,
    bricks: l,
    width: letter[2],
  };
}

async function callAnalyze(text, l) {
  //TODO: send through prefix and suffix as well?
  
  const url = new URL(`${APIHOST}/analyze`);
  url.searchParams.set('start', currentSeg.value.start);
  url.searchParams.set('end', currentSeg.value.end);
  if (!currentSeg.value.isRetry) {
    url.searchParams.set('sent', currentSent);
  }
  url.searchParams.set('text', text);
  if (checked.value && text == '') {
    url.searchParams.set('beam', 'true');
  }
  const r = await fetch(url);
  if (!r.ok) {
    addMessage("ERROR: analysis returned " + r.status);
    return null;  
  } 
  const data = await r.json(); // currently receive a dict: list=,phones=..
  l.value.list = data.list.map(mapBricks);
  l.value.active = -1;
  linkSynthAudio(data.phones, l.value.playerID);
  return data;
}

async function getLetters() {
  try { // catch errors as this is top level call
    isAnalyzing.value=true;
    prefix.value = wordsBeforeStart(currentSeg.value.start, currentSent);
    suffix.value = wordsAtEnd(currentSeg.value.end, currentSent); // could even move this logic earlier.
    if (currentSeg.value.isRetry) {
      currentSeg.value.isRetry = false;
      updateSeg();
    }

    const _data = await callAnalyze(currentSeg.value.text, pho);
    pho.value.text = currentSeg.value.text;

    if (correctText.value) {
      const _data2 = await callAnalyze(correctText.value, corr)
    }
    else {
      corr.value.list = []
    }
    corr.value.text = correctText.value;

    const data3 = await callAnalyze("", raw);
    raw.value.text = data3.phones;

    if (!infoDictionary) {
      const response = await fetch(`${APIHOST}/phoneme_info`)
      if (!response.ok) {
        throw new Error(`problem loading info: ${response.status} ${response.statusText}`);
      }
      infoDictionary = await response.json();
    }
  }
  catch (error) {
    addMessage(error.message);
  }
  finally {
    isAnalyzing.value = false;
  }
}

async function callRetry() {
  //ensure text messages are arriving at log file before we ask to do recognition (avoid race)
  if (progressSource == null || progressSource.readyState === EventSource.CLOSED) {
     await AwaitLogInit();
  }
  const formData = new FormData();
  formData.append("prefix", prefix.value);
  formData.append("suffix", suffix.value);
  formData.append("is_sentence", radioFullSentence.value);
  formData.append("sent", currentSent);
  formData.append("orig_seg_start", currentSeg.value.start);
  formData.append("orig_seg_end", currentSeg.value.end);
  formData.append("audio", reRecorder.value.blob, 'audio.wav');

  const r = await fetch(`${APIHOST}/retry`, {
    method: 'POST',
    body: formData
  });
  if (!r.ok) {
    throw new Error("analysis returned " + r.status);
  }
  const data = await r.json(); // currently receive a dict: text=,start=,
  //probably don't want to update seg text? Confusion with analyze in UI?
  //currentSeg.value.text=data.text; 
  currentSeg.value.start = data.start;
  currentSeg.value.end = data.end;
  currentSeg.value.isRetry = true;
  segAudioPlayer.value.src = ReRecAudioPlayer.value.src;
  segAudioPlayer.value.currentTime = currentSeg.value.start;
  return data;
}

async function getRetry() {
  try { // catch errors as this is top level call
    //rerecognize audio first
    const retryData = await callRetry();
    pho.value.text = retryData.text;

    //now update two of the three analysis panels, like getLetters() does.
    //correct panel does not change
    const _data = await callAnalyze(pho.value.text,pho);

    const data2 = await callAnalyze("", raw);
    raw.value.text = data2.phones;
  }
  catch (error) {
    addMessage(error.message);
  }
}

function linkDictionary(ph, index, struct, idPrefix) {
  let i;
  let e = document.getElementById(idPrefix + ".Dict");
  e.href = infoDictionary[ph][0];
  const array = infoDictionary[ph][1].split(' ');
  for (i = 0; i < array.length && i < 3; i += 1) {
    e = document.getElementById(idPrefix + ".WAudio" + String(i + 1));
    e.preload = 'none';
    e.src = array[i];
    e.controls = false;
  }
  struct.active = index;
  struct.info = "Phoneme " + ph + ": " + infoDictionary[ph][2];
  struct.nButtons = array.length
  return struct;
}

</script>
<template>
  <div class="bg-white rounded-3 border border-2 border-slate-200 shadow-sm ">
    <div class="container text-center justify-content-center">
      <h2 class="text-center">
        Record Audio.
      </h2>
      <div class="row pb-1 justify-content-center">
        <div class="col-auto">
          Language:
        </div>
        <div class="col-auto">
          <select id="langselect" class="form-select-sm">
            <option selected value="">
              Automatic
            </option>
            <option value="pt">
              Portuguese
            </option>
            <option value="en">
              English
            </option>
          </select>
        </div>
        <div class="col-auto">
          Model size:
        </div>
        <div class="col-auto">
          <select id="modelselect" class="form-select-sm">
            <option value="tiny">
              Tiny
            </option>
            <option value="small">
              Small
            </option>
            <option value="large-v3-turbo">
              Large Turbo
            </option>
          </select>
        </div>
      </div>
      <!-- <div class="row justify-content-sm-center">
      <div class="col-sm-auto">
       Available:{{ isAudioAvail }} Recording Now:{{ isRecordingNow }} Paused:{{ isRecordingPaused }} 
   </div> 
       </div> -->
      <div class="myaudio">
        <div v-if="mainRecorder.isRecordingNow">
          RECORDING
        </div>
        <div v-else-if="mainRecorder.isRecordingPaused">
          PAUSED
        </div>
        <div v-show="mainRecorder.isAudioAvail">
          <audio id="RecAudioPlayer" ref="RecAudioPlayer" preload="none" controls></audio>
        </div>
      </div>
      <p class="text-center">
        <button class=" btn btn-secondary" :disabled="!mainRecorder.isAudioAvail && !mainRecorder.isRecordingPaused"
          @click="clearAudio(mainRecorder)">
          <font-awesome-icon icon="circle-xmark" /> Clear
        </button>
        <button class="btn btn-danger"
          @click="mainRecorder.isRecordingNow ? soundPause(mainRecorder) : soundRecord(mainRecorder)">
          <font-awesome-icon :icon="mainRecorder.isRecordingNow ? 'circle-pause' : 'microphone'" />
          {{ mainRecorder.isRecordingNow ? "Pause" : "Record" }}
        </button>
        <button class="btn btn-secondary" :disabled="!mainRecorder.isRecordingNow && !mainRecorder.isRecordingPaused"
          @click="soundStop(mainRecorder)">
          <font-awesome-icon icon="circle-stop" />
          Stop
        </button>
        <button class="btn btn-secondary" :disabled="!mainRecorder.isAudioAvail" @click="doRecog()">
          <font-awesome-icon icon="circle-check" />
          {{ isRecognizing? "Recognizing..." : "Recognize" }}
        </button>
        <button class="btn btn-secondary" @click="makePreset()">
          Preset
        </button>
      </p>
    </div>
  </div>
  <!---- WORD LIST PANEL ---->
  <div v-show="wordsList.length > 0" class="bg-white rounded-3 border border-2 border-slate-200 shadow-sm "
    style="margin-top:10px">
    <span justify-content="left">{{ onlyPartialWords ? "Click to correct words, or wait for analysis:" :
      "Click on words to analyze and correct:" }}</span>
    <button justify-content="right" class="btn btn-secondary myclearbutton" @click="wordListToClipboard()">
      <font-awesome-icon icon="copy" />
    </button>
    <button justify-content="right" class="btn btn-secondary myclearbutton" @click="wordListReset()">
      <font-awesome-icon icon="circle-xmark" />
    </button>
    <div class="container " style="flex-wrap: wrap; min-height: 120px">
      <button v-for="(word, index) in wordsList" :key="`w-${index}`"
        class="px-2.5 py-2.5 rounded-3 fw-bold border text-start align-items-center gap-2 select-none" :class="word.active ? 'token-btn-active' :
          word.disabled ? 'token-btn-disabled' : word.unlikely ? 'token-btn-unlikely' : 'token-btn'"
        @click="toggleAndUpdateSeg(word)">
        {{ word.disabled ? word.correction : word.text }}
      </button>
    </div>
  </div>
  <!--CORRECTION PANEL -->
  <div v-show="currentSeg.text" class="bg-white container rounded-3 border border-2 border-slate-200 shadow-sm ">
    Correction for <strong>{{ currentSeg.text }} </strong> :
    <div class="hstack gap-1">
      <input v-model="correctText" type="text" name="corrText" class="form-control" :placeholder="currentSeg.text" />
      <button class="btn btn-primary" :disabled="onlyPartialWords || isAnalyzing" @click="getLetters">
        {{isAnalyzing?"Analyzing...":"Analyze"}} 
      </button>
      <button class="btn btn-secondary" :disabled="(correctText == '' && !currentSeg.more)" @click="correctWordsList">
        Continue
      </button>
      <button class="text-nowrap btn btn-secondary" @click="playAudioInside">
        <font-awesome-icon icon="circle-play" /> <audio id="segAudioPlayer" ref="segAudioPlayer"> </audio> Clip
      </button>
    </div>
  </div>
  <!---- LETTERS LIST PANEL ---->
  <!--BEST GUESS-->
  <div v-show="pho.list.length > 0" class="bg-white rounded-3 border border-2 border-slate-200 shadow-sm"
    @click="pho.active = -1">
    <div class="container d-flex justify-content-between align-items-top">
      <h5>Best Guess</h5>
      <span> {{ pho.text }}</span> <!--TODO: <span> Distance /Confidence</span> -->
      <button class="btn btn-secondary" @click.stop="playAudioInside">
        <font-awesome-icon icon="circle-play" /> <audio id="phoID.AudioPlayer"></audio> Synth
      </button>
    </div>
    <div class="container d-flex">
      <div v-for="(l, index) in pho.list" :key="`ph-${index}`" class="col myletter" :style="{ 'flex-grow': l.width }"
        @click.stop="pho = linkDictionary(l.text, index, pho, 'phoID')">
        <div v-for="(brick, index2) in l.bricks" :key="`ph-${index}-${index2}`" class="row" :class="brick">
        </div>
        <div :class="index == pho.active ? 'myphoneme-active' : 'myphoneme'">
          {{ l.text }}
        </div>
      </div> 
    </div>
    <div v-show="pho.active >= 0" @click.stop="">
      <div class="container d-flex flex-nowrap justify-content-between align-items-center">
        <div> {{ pho.info }} </div>
        <div class="text-end">
          <a id="phoID.Dict" href="" target="wikiTab">Wikipedia</a>
          <button class="btn btn-secondary" @click.stop="playAudioInside">
            <font-awesome-icon icon="circle-play" />Wiki<audio id="phoID.WAudio1"></audio>
          </button>
          <button v-show="pho.nButtons > 1" class="btn btn-secondary" @click="playAudioInside">
            <font-awesome-icon icon="circle-play" />(2)<audio id="phoID.WAudio2"></audio>
          </button>
          <button v-show="pho.nButtons > 2" class="btn btn-secondary" @click="playAudioInside">
            <font-awesome-icon icon="circle-play" />(3)<audio id="phoID.WAudio3"></audio>
          </button>
        </div>
      </div>
    </div>
    <hr />
    <!--CORRECT ANSWER-->
    <div v-show="corr.list.length > 0" @click="corr.active = -1">
      <div class="container d-flex justify-content-between align-items-top">
        <h5>Correct Answer</h5>
        <span>{{ corr.text }}</span>
        <button class="btn btn-secondary" @click.stop="playAudioInside">
          <font-awesome-icon icon="circle-play" /> <audio id="corrID.AudioPlayer"> </audio>Synth
        </button>
      </div>
      <div class="container d-flex">
        <div v-for="(l, index) in corr.list" :key="`cor-${index}`" class="col myletter"
          :style="{ 'flex-grow': l.width }" @click.stop="corr = linkDictionary(l.text, index, corr, 'corrID')">
          <div v-for="(brick, index2) in l.bricks" :key="`cor-${index}-${index2}`" class="row" :class="brick">
          </div>
          <div :class="index == corr.active ? 'myphoneme-active' : 'myphoneme'">
            {{ l.text }}
          </div>
        </div>
      </div>
      <div v-show="corr.active >= 0" @click.stop="">
        <div class="container d-flex flex-nowrap justify-content-between align-items-center">
          <div>{{ corr.info }}</div>
          <div class="text-end">
            <a id="corrID.Dict" href="" target="wikiTab">Wikipedia</a>
            <button class="btn btn-secondary" @click.stop="playAudioInside">
              <font-awesome-icon icon="circle-play" />Wiki<audio id="corrID.WAudio1"></audio>
            </button>
            <button v-show="corr.nButtons > 1" class="btn btn-secondary" @click="playAudioInside">
              <font-awesome-icon icon="circle-play" />(2)<audio id="corrID.WAudio2"></audio>
            </button>
            <button v-show="corr.nButtons > 2" class="btn btn-secondary" @click="playAudioInside">
              <font-awesome-icon icon="circle-play" />(3)<audio id="corrID.WAudio3"></audio>
            </button>
          </div>
        </div>
      </div>
    </div>
    <hr />
    <!--RAW ANSWER-->
    <div v-show="raw.list.length > 0" @click="raw.active = -1">
      <div class="container d-flex justify-content-between align-items-top">
        <h5>Raw Answer</h5> <span>{{ raw.text }}</span>
        <button id="rawSynth" class="btn btn-secondary" @click="playAudioInside">
          <font-awesome-icon icon="circle-play" /> <audio id="rawID.AudioPlayer"> </audio>Synth
        </button>
      </div>
      <div class="container d-flex flex-wrap">
        <div v-for="(l, index) in raw.list" :key="`raw-${index}`" class="col myletter" :style="{ 'flex-grow': l.width }"
          @click.stop="linkDictionary(l.text, index, raw, 'rawID')">
          <div v-for="(brick, index2) in l.bricks" :key="`raw-${index}-${index2}`" class="row" :class="brick">
          </div>
          <div :class="index == raw.active ? 'myphoneme-active' : l.text == '' ? 'myphoneme-blank' : 'myphoneme'">
            {{
              l.text }}
          </div>
        </div>
      </div>
      <div v-show="raw.active >= 0" @click.stop="">
        <div class="container d-flex flex-nowrap justify-content-between align-items-center">
          <div>{{ raw.info }}</div>
          <div class="text-end">
            <a id="rawID.Dict" href="" target="wikiTab">Wikipedia</a>
            <button class="btn btn-secondary" @click="playAudioInside">
              <font-awesome-icon icon="circle-play" />Wiki<audio id="rawID.WAudio1"></audio>
            </button>
            <button v-show="raw.nButtons > 1" class="btn btn-secondary" @click="playAudioInside">
              <font-awesome-icon icon="circle-play" />(2)<audio id="rawID.WAudio2"></audio>
            </button>
            <button v-show="raw.nButtons > 2" class="btn btn-secondary" @click="playAudioInside">
              <font-awesome-icon icon="circle-play" />(3)<audio id="rawID.WAudio3"></audio>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
  <!--TODO: TIPS GO HERE-->
  <!--TODO: RERECORD PANEL-->
  <div v-show="corr.text != ''" class="bg-white rounded-3 border border-2 border-slate-200 p-3 shadow-sm">
    <div class="d-flex align-items-start justify-content-between rounded bg-white">
      <button class="btn btn-danger text-nowrap"
        @click="reRecorder.isRecordingNow ? soundStop(reRecorder) : soundRecord(reRecorder)">
        <font-awesome-icon :icon="reRecorder.isRecordingNow ? 'circle-stop' : 'microphone'" />
        {{ reRecorder.isRecordingNow ? "Stop" : "ReRecord" }}
        <audio id="ReRecAudioPlayer" ref="ReRecAudioPlayer"></audio>
      </button>
      Carefully repeat one of the options below.
      <div>
        <button class="btn btn-secondary px-4 text-nowrap" :disabled="!reRecorder.isAudioAvail" @click="getRetry()">
          <font-awesome-icon icon="circle-check" /> Retry
        </button>
      </div>
    </div>
    <div class="form-check">
      <input id="radio1" v-model="radioFullSentence" class="form-check-input" type="radio" name="radioReRec"
        :value="false" />
      <label class="form-check-label d-block text-wrap" for="radio1">
        &ldquo;{{ corr.text }}&rdquo;
      </label>
    </div>
    <div class="form-check">
      <input id="radio2" v-model="radioFullSentence" class="form-check-input" type="radio" name="radioReRec"
        :value="true" />
      <label class="form-check-label d-block text-wrap" for="radio2">
        &ldquo;{{ prefix }} {{ corr.text }} {{ suffix }}&rdquo;
      </label>
    </div>
    <div class="form-check">
      <input id="checkbox" v-model="checked" type="checkbox" />
      <label for="checkbox">{{ checked }}</label>
    </div>
  </div>
  <!---- PROGRESS LOG PANEL ---->
  <div class="bg-light w-100  rounded-3 border border-2 border-slate-200 shadow-sm">
    <p>Server Info:</p>
    <div ref="scrollContainer" style="height: 120px; scroll-behavior: smooth;"
      class="bg-light overflow-y-scroll w-100 ">
      <div v-for="(message, index) in messages" :key="`mess-${index}`"
        class="text-muted font-monospace small ps-1 lh-1">
        {{ message }}
      </div>
    </div>
  </div>
  <div v-show="raw.list.length > 0" font-size="-2">
    <footer class="text-muted small-caps-legal lh-sm ps-2">
      Copyright 2026 SFK made with WhisperX + Espeak + Piper + Wav2Vec2 + Flask + VueJS. Includes links to audio
      files from <a href="https://commons.wikimedia.org/wiki/Main_Page">Wikimedia Commons</a> under the terms of the
      <a href="https://creativecommons.org/licenses/by-sa/3.0/deed.en">Creative
        Commons Attribution-Share Alike 3.0 Unported</a> license. See documentation.
    </footer>
  </div>
 <!-- <RouterView /> -->
</template>

<style>
#app {
  margin-top: 10px
}

body {
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  background-color: #f1f5f9;
}

/* Custom interactive word/token button styling */
.border-slate-200 {
  border-color: #e2e8f0 !important;
}

.token-btn {
  background-color: #f8fafc !important;
  border-color: #e2e8f0 !important;
  color: #334155 !important;
  transition: all 0.15s ease-in-out;
  margin: 2px
}

.token-btn-unlikely {
  background-color: #f8fafc !important;
  border-color: #e2e8f0 !important;
  color: #8f8f8f !important;
  font-style: italic;
  margin: 2px
}

.token-btn:hover {
  background-color: #f1f5f9 !important;
  border-color: #cbd5e1 !important;
  color: #0f172a !important;
}

.token-btn-active {
  background-color: #4f46e5 !important;
  border-color: #4f46e5 !important;
  color: #ffffff !important;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
  transition: all 0.15s ease-in-out;
  margin: 2px
}


.token-btn-disabled {
  background-color: #ffffff !important;
  border-color: #ffffff !important;
  color: green !important;
  box-shadow: none;
  transition: none;
  margin: 0
}


.token-btn-active:hover {
  background-color: #4338ca !important;
  border-color: #4338ca !important;
  color: #ffffff !important;
}

/* Indicators */
.indicator-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  display: inline-block;
}

.myaudio {
  height: 54px;
}

.brickfill {
  width: auto;
  height: 6px;
  background-color: #2a66ff;
  margin: 2px;
}

.brickempty {
  width: auto;
  height: 6px;
  margin: 2px;
}

.myclearbutton {
  float: right;
}

.myphoneme {
  background-color: #e2e8f0;
  text-align: center;
  border-style: solid;
  border-color: #e2e8f0;
  font-weight: bold;
}

.myphoneme-blank {
  background-color: white;
  border-style: solid;
  border-color: white;
}

.myphoneme-active {
  background-color: #e2e8f0;
  border-style: solid;
  border-color: #303030;
  text-align: center;
  font-weight: bold;
}

.myphoneme:hover {
  background-color: #adb0b4;

}

.myletter {
  margin: 2px;
  flex-basis: auto;
  flex-shrink: 1;
  width: auto;
}


.indicator-dot-active {
  background-color: #10b981 !important;
  box-shadow: 0 0 6px rgba(16, 185, 129, 0.9);
}

.indicator-dot-inactive {
  background-color: #cbd5e1 !important;
}

.small-caps-legal {
  font-variant: small-caps;
  font-size: 0.75rem;
  letter-spacing: 0.05em;
}

.small-caps {
  font-variant: small-caps;
  letter-spacing: 0.05em;
}

.btn {
  margin: 2px;
}

.hover-bg:hover {
  background-color: #e2e8f0 !important;
}

.hover-entry:hover {
  border-color: #334155 !important;
  background-color: #1e293b !important;
}

.btn-reset-style {
  background: none;
  cursor: pointer;
}

.btn-reset-style:focus {
  outline: none;
}

.hover-light:hover {
  background-color: #f8fafc !important;
}

.focus-outline:focus {
  outline: none;
  border-color: #6366f1 !important;
}
</style>