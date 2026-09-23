import heapq
import logging
import sys
import threading
from collections import Counter
from itertools import accumulate, groupby

import phonemizer
from rapidfuzz import fuzz

from flask import current_app

BLOCKNOS = 5.0 # Number to multiply score by for UI.

phonemizer_lock = threading.Lock()

wordlist = [
    {"word": "Rotei", "start": 0.312, "end": 0.513, "sent": 0, "idx": 0},
    {"word": "que", "start": 0.533, "end": 0.613, "sent": 0, "idx": 1},
    {"word": "primeiro.", "start": 0.674, "end": 1.155, "sent": 0, "idx": 2},
    {"word": "Todos", "start": 1.738, "end": 1.959, "sent": 1, "idx": 3},
    {"word": "os", "start": 1.979, "end": 2.019, "sent": 1, "idx": 4},
    {"word": "seres", "start": 2.059, "end": 2.28, "sent": 1, "idx": 5},
    {"word": "humanos", "start": 2.3, "end": 2.641, "sent": 1, "idx": 6},
    {"word": "nascem", "start": 2.702, "end": 3.003, "sent": 1, "idx": 7},
    {"word": "livros", "start": 3.063, "end": 3.445, "sent": 1, "idx": 8},
    {"word": "e", "start": 3.525, "end": 3.565, "sent": 1, "idx": 9},
    {"word": "iguais,", "start": 3.585, "end": 4.027, "sent": 1, "idx": 10},
    {"word": "em", "start": 4.087, "end": 4.167, "sent": 1, "idx": 11},
    {"word": "dignidade", "start": 4.208, "end": 4.81, "sent": 1, "idx": 12},
    {"word": "e", "start": 4.85, "end": 4.91, "sent": 1, "idx": 13},
    {"word": "em", "start": 4.95, "end": 5.011, "sent": 1, "idx": 14},
    {"word": "direitos.", "start": 5.051, "end": 5.593, "sent": 1, "idx": 15},
    {"word": "Doutado", "start": 6.075, "end": 6.436, "sent": 2, "idx": 16},
    {"word": "se", "start": 6.456, "end": 6.497, "sent": 2, "idx": 17},
    {"word": "trazá-lo", "start": 6.517, "end": 6.938, "sent": 2, "idx": 18},
    {"word": "de", "start": 6.958, "end": 7.019, "sent": 2, "idx": 19},
    {"word": "consciência,", "start": 7.059, "end": 7.762, "sent": 2, "idx": 20},
    {"word": "devem", "start": 7.902, "end": 8.123, "sent": 2, "idx": 20},
    {"word": "agir", "start": 8.163, "end": 8.384, "sent": 2, "idx": 21},
    {"word": "uns", "start": 8.424, "end": 8.585, "sent": 2, "idx": 22},
    {"word": "por", "start": 8.645, "end": 8.786, "sent": 2, "idx": 23},
    {"word": "com", "start": 8.866, "end": 8.986, "sent": 2, "idx": 24},
    {"word": "os", "start": 9.027, "end": 9.147, "sent": 2, "idx": 25},
    {"word": "outros", "start": 9.207, "end": 9.468, "sent": 2, "idx": 26},
    {"word": "em", "start": 9.569, "end": 9.649, "sent": 2, "idx": 27},
    {"word": "espírito", "start": 9.689, "end": 10.031, "sent": 2, "idx": 28},
    {"word": "de", "start": 10.051, "end": 10.091, "sent": 2, "idx": 29},
    {"word": "fatraidade.", "start": 10.111, "end": 11.135, "sent": 2, "idx": 30},
]


def prettify_head(result: dict) -> str:
    if not result.get("segments", None):
        return ""
    if not result["segments"][0]:
        return ""
    if not result["segments"][0].get("text", None):
        return ""
    t = result["segments"][0]["text"]
    return t[0:80]


# from a words list with timings, return string of words between start and end, plus
# definitive boundaries of these words.
def chop_text_from_words(
    r: list[dict], start: float, end: float
) -> tuple[str, float, float]:
    text = ""
    first = -1
    last = -1
    for w in r:
        w_start = float(w["start"])
        w_end = float(w["end"])
        mid = w_start + 0.5 * (w_end - w_start)
        if mid > start and mid < end:
            text += w["word"] + " "
            if first < 0:
                first = w_start
            last = w_end
        if w_end >= end:
            break
    return text, first, last


# Like make_words_list, but less detail, and no sentence index.
def make_partial_resultlist(partial: list[dict]) -> list[dict]:
    i = 0
    result = []
    for x in partial:
        words = x["text"].split()
        for wrd in words:
            w = {"word": wrd}
            w["idx"] = i
            result.append(w)
            i += 1
    return result


# turn the whisperx nested result into a flat list of words, + sentence index

def make_words_list(result: list[dict]) -> tuple[list[int], list[dict]]:
    sentences = []  # starting word index for each sentence
    words = []  # timing, sent number and index number for each word, in flat list.
    i = 0
    for snt in result:
        sentences.append(i)
        for wrd in snt["words"]:
            w = wrd  # already has 'word','start','end'
            w["orig_score"] = round(w["score"], 3)
            w["score"] = round(w["score"] ** (1 + 0.2 * len(w["word"])), 3)
            w["sent"] = len(sentences) - 1
            w["idx"] = i
            w["unlikely"] = 0
            i += 1
            words.append(w)
    return sentences, words


# set 'unlikely' flag for words in list with lowest probabilities
def mark_unlikely(words: list[dict]):
    ln = len(words)
    h = [(w["score"], idx) for idx, w in enumerate(words)]
    heapq.heapify(h)
    count_unlikely = 0
    while count_unlikely < min(ln / 3, 2):
        if h[0][0] > 0.80:
            break  # never show high probs
        if h[0][0] > 0.50 and count_unlikely > min(ln / 10, 2):
            break
        lowest_word_idx = heapq.heappop(h)[1]
        count_unlikely += 1
        words[lowest_word_idx]["unlikely"] = 1


#Make minimal list to send to javascript: call this fn with map()
def to_basiclist(x: dict) -> list:  # for each phoneme, record its text, score and length
    return [x["text"], round(x["score"] * BLOCKNOS, 3), x["end"] - x["start"]]

#Reverse of to_list: turn it back into a full list with starts and ends
def unpack_phonlist( x: list[list]) -> list[dict]:
    lengths = [item[2] for item in x]
    ends = list(accumulate(lengths))
    starts = [0] + ends[:-1]
    result = [
        {"text": item[0], "score": item[1] / BLOCKNOS, "start": start, "end": end}
        for item, start, end in zip(x, starts, ends)
    ]
    return result


def dipthong(d: str,phonemes:dict ) -> bool:
    if " " in phonemes[d][1] :
        current_app.logger.info(f"{d=} {phonemes[d][1]=}")
    return " " in phonemes[d][1]

#are sounds a and b a close match?
def close_attempt(a:dict, b:dict,phonemes:dict) -> bool:  # a is correct, b is attempt

    if a['text']=='' or b['text']=='':
        return False
    if a["score"] > b["score"]:
        return False  # ignore a less likely attempt
    ignore = ("long", "nasalized", "lowered", "r-coloured","schwa","unreleased")
    # for description alternatives set =('voiced:[('voiceless','remove voicing')],
    #                           'central',[('back','move back'),('front','move front')])
    # take advantage of dictionary order correct vs attempt, construct description.
    alternatives = (
        "voiced",
        "voiceless",
        "close",
        "close-mid",
        "open",
        "near-open",
        "open-mid",
        "rounded",
        "unrounded",
        "mid-central",
        "front",
        "central",
        "back",
    )
    ap = a["text"] 
    bp = b["text"]
    if ap == bp or dipthong(ap,phonemes) or dipthong(bp,phonemes):
        return False
    
    a_desc=phonemes[ap][2].split() # eg ['open','front','vowel']
    b_desc=phonemes[bp][2].split()

    attrs = Counter(b_desc)
    attrs += Counter(a_desc)
    current_app.logger.info(f"{attrs=}")
    for i in attrs:
        if attrs[i] == 1 and i not in ignore:
            current_app.logger.info(f"{ap} {bp} {i}")
            if i not in alternatives:
                return False
    return True


def  create_tips(corr:list[dict],best:list[dict],raw:list[dict],phonemes:dict):
    c = b = r = 0 
    corr_len,best_len,raw_len=len(corr),len(best),len(raw)
   
    tips = []
    now=0
    #c_start=b_start=r_start=0
    while c<corr_len or b<best_len or r<raw_len:
   
        current_app.logger.info(f" Comparing at time {now=}")
  
        c_inrange:bool=c<corr_len and corr[c]['start']<=now and corr[c]['end']>now
        b_inrange=b<best_len and best[b]['start']<=now and best[b]['end']>now
        r_inrange=r<raw_len and raw[r]['start']<=now and raw[r]['end']>now    

        if c_inrange:
            current_app.logger.info(f" corr = {corr[c]['text']}")
        if b_inrange:
            current_app.logger.info(f" best = {best[b]['text']}")
        if r_inrange:
            current_app.logger.info(f" raw = {raw[r]['text']}")
        b_is_close=close_attempt(corr[c],best[b],phonemes) if b_inrange and c_inrange else False
        if c_inrange and b_inrange and b_is_close:
            attempt = raw[r]["text"] if r_inrange and close_attempt(corr[c], raw[r],phonemes) else best[b]["text"]
            tips.append(f"Adjust your speech from {attempt} to {corr[c]['text']}")
        elif ((not c_inrange or not b_is_close) and 
                b_inrange and r_inrange and 
                close_attempt(corr[c],raw[r],phonemes)):
            tips.append(f"Your {corr[c]['text']} was more like {raw[r]['text']}")

        c_end = corr[c]['end'] if c < corr_len else float("inf")
        b_end = best[b]['end'] if b < best_len else float("inf")
        r_end = raw[r]['end'] if r < raw_len else float("inf")
        now=min([c_end,b_end,r_end])
        if c_inrange and c_end==now:
            c+=1 #  would not be valid if we had gaps 
        if b_inrange and b_end==now:
            b+=1
        if r_inrange and r_end==now:
            r+=1
        
    return [key for key, group in groupby(tips)] #dedupe tips

#### Phonemizer -related functions

trans = str.maketrans("", "", ":;/.,!\"'")

def strip_punc(x: str) -> str:
    return x.translate(trans) # strip the basics including commas - we might put commas back in as a last resort

# phonemize_words: Uses phonemizer+espeak to convert text to phonemes,
# where listof3=[prefix,text,suffix] to give the rest of the sentence as context.
# We identify target text within espeak's output by word counting.
# If we think this would fail due to espeak joining or splitting words, back off to inferior strategy.

def phonemize_words(listof3: list[str], lang: str) -> str:

    listof3 = list(map(strip_punc, listof3))
    listoflist = [x.split() for x in listof3]
    word_counts = list(map(len, listoflist))
    word_count_sum = sum(word_counts)
    gen_lang = lang
    if lang == "en":
        gen_lang = "en-gb"
    sentence = " ".join(map(" ".join, listoflist))

    with phonemizer_lock:
        phn: str = phonemizer.phonemize(
            sentence,
            language=gen_lang,
            backend="espeak",
            separator=phonemizer.separator.Separator(phone=" ", word="\t"),  # type: ignore
        )
    phnlist: list = phn.split("\t")
    if (
        phnlist[-1] == ""
    ):  # split with argument '\t' makes a trailing empty entry. Delete it.
        phnlist.pop()
    if len(phnlist) != word_count_sum:
        logger=logging.getLogger("DAL")
        logger.info(
            "warning, word counts %d, %d do not match for %s %s, backing off",
            word_count_sum,
            len(phnlist),
            listof3,
            phnlist,
        )
        return phonemize_backoff(listof3, gen_lang)
    return " ".join(phnlist[word_counts[0] : word_counts[0] + word_counts[1]])


def phonemize_backoff(listof3: list[str], gen_lang: str) -> str:

    with phonemizer_lock:
        phn: str = phonemizer.phonemize(
            listof3[0] + " , " + listof3[1] + " , " + listof3[2],
            language=gen_lang,
            backend="espeak",
            separator=phonemizer.separator.Separator(phone=" ", word="\t"),  # type: ignore
            preserve_punctuation=True,
        )
    current_app.logger.info(f"Backoff result: {phn}")
    phn = phn.replace("\t", " ")
    l = phn.split(",")
    return l[1].strip()  # if needed can also return l[0] + l[1] + l[2]


def split_by_fuzzy_match(
    words: list[dict], prefix: str, suffix: str
) -> tuple[float, float]:

    target_end_idx = None
    current_app.logger.info(f"Attempting fuzzy match {words=} {prefix=} {suffix=}")
    if prefix == "":
        start = words[0]["start"]
        target_start_idx = 0
    else:
        match = ""
        best_score = 0.0
        for idx, w in enumerate(words):
            if idx == len(words) - 1:
                break
            match += w["word"] + " "
            if fuzz.ratio(match, prefix) > best_score:
                target_start_idx = idx + 1
        start = words[target_start_idx]["start"]
    if suffix == "":
        end = words[-1]["end"]
    else:
        match = ""
        best_score = 0.0
        idx = len(words) - 1
        while idx > target_start_idx:
            match = words[idx]["word"] + " " + match
            if fuzz.ratio(match, suffix) > best_score:
                target_end_idx = idx - 1
            idx -= 1
        if target_end_idx == None:  # disastrous matching fail?
            target_end_idx = len(words) - 1  # perhaps user only spoke seg not sentence.
            logger=logging.getLogger("DAL")
            print(f"Match failed: {match}",file=sys.stderr)
            logger.info("Could not match sentence")
        end = words[target_end_idx]["end"]
        current_app.logger.info(f"seg is between {target_start_idx} and {target_end_idx} in {words}")
    return start, end

# Return surrounding words in the same sentence, given start and end time.
def build_context(sent_idx: int, words: list, start_time: float, end_time: float):
    sent_no = words[sent_idx]["sent"]
    i = sent_idx
    prefix: str = ""
    suffix: str = ""
    while i < len(words) and words[i] and words[i]["sent"] == sent_no:
        if words[i]["end"] <= start_time:
            prefix += words[i]["word"] + " "
        elif words[i]["start"] >= end_time:
            suffix += words[i]["word"] + " "
        i += 1
    return prefix, suffix


def get_sent_bounds(
    i: int, sentences: list[int], words: list[dict]
) -> tuple[float, float]:
    start = end = 0.0
    w: int = sentences[i]
    start: float = words[w]["start"]
    while w < len(words) and words[w]["sent"] == i:
        end: float = words[w]["end"]
        w += 1
    return start, end
