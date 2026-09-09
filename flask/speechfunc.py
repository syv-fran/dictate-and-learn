import logging
from dataclasses import dataclass

import numpy
import torch
import torch.nn.functional as F
import torchaudio
import transformers
from torchaudio.models.decoder import ctc_decoder


@dataclass(frozen=True)
class PhoneAligner:
    model: transformers.Wav2Vec2ForCTC
    tokenizer: transformers.Wav2Vec2PhonemeCTCTokenizer
    sample_rate: int
    frame_duration: float
    device: str

def load_phone_aligner(model_dir: str, local_only: bool, device: str) -> PhoneAligner:
    model_name = "facebook/wav2vec2-xlsr-53-espeak-cv-ft"
    p_model = transformers.Wav2Vec2ForCTC.from_pretrained(
        model_name, cache_dir=model_dir, local_files_only=local_only
    )
    feature_extractor = transformers.Wav2Vec2FeatureExtractor.from_pretrained(
        model_name,
        cache_dir=model_dir,
        local_files_only=local_only,
    )
    p_tokenizer = transformers.Wav2Vec2PhonemeCTCTokenizer.from_pretrained(
        model_name,
        cache_dir=model_dir,
        local_files_only=local_only,
    )
    print(f" {p_tokenizer} ")
    sample_rate = feature_extractor.sampling_rate
    stride_samples = p_model.config.inputs_to_logits_ratio
    return PhoneAligner(model=p_model, tokenizer=p_tokenizer, 
                        sample_rate=sample_rate,
                        frame_duration= stride_samples / sample_rate,
                        device=device)


def tokenpath_to_spans(
    aligned_tokens: torch.Tensor,
    scores: torch.Tensor,
    pa: PhoneAligner,
    start_time_offset: float
) -> list:
    current_nonblank_token:int|None = None
    start_frame:int|None = None
    first_blank:int|None = None
    active_count:int = 0
    prob_sum = 0.0
    phoneresult = []

    # we merge things ourselves because torch's merge tokens doesn't include
    # blanks in the span. this also allows us to choose different calculations for scoring.
    
    for i, token in enumerate(aligned_tokens):
        if token == pa.tokenizer.pad_token_id:
            if first_blank == None:  # and not starting_new_word(....)
                first_blank = i
        else:
            # finalize if we're not at start + we've changed token, or 
            # we have the same token after an intervening gap
            # absorbing blanks into left token : g g -> g, g blanks x -> g x, g blank g -> g g
            if (start_frame is not None and
                    (token != current_nonblank_token or first_blank is not None)):
                assert active_count > 0, "empty speech???"
                assert current_nonblank_token is not None
                phoneresult.append(
                    {
                        "text": pa.tokenizer.decode([current_nonblank_token]),
                        "start": round(start_time_offset + pa.frame_duration * start_frame, 4),
                        "end": round(start_time_offset + pa.frame_duration * i, 4),
                        # "score": round(torch.mean(scores[start_frame:i]).item(),3) #what whisper does
                        "score": round(prob_sum / active_count, 3),
                    }
                )
                start_frame = i
                active_count = 0
                prob_sum = 0.0
            if start_frame is None:
                start_frame = i
            first_blank = None
            current_nonblank_token = int(token.item())
            prob_sum += scores[i].item()
            active_count += 1
    if current_nonblank_token is not None:
        #   if (first_blank is not None):
        #      i=first_blank #set this for no trailing blanks in final result
        assert active_count > 0, "empty speech at end???"
        assert start_frame is not None
        phoneresult.append(
            {
                "text": pa.tokenizer.decode([current_nonblank_token]),
                "start": round(start_time_offset + pa.frame_duration * start_frame, 4),
                "end": round(start_time_offset + pa.frame_duration * (i+1), 4),
                #  "score": round(torch.mean(scores[start_frame:i+1]).item(),3)
                "score": round(prob_sum / active_count, 3),
            }
        )
    return phoneresult

# crop_highlight_end is only useful after beam search extension... can use found_phones if we have it.
#  adjust last entry in highlight when part of a whole sentence, to make it the same.

def crop_highlight_end(l, end, found_phones):

    for c in l:
        if c["start"] < end and c["end"] > end:
            mid = (c["end"] - c["start"]) / 2
            if c["char"] == found_phones[-1] or c["start"] + mid < end:
                c["end"] = end
            else:
                c["start"] = end
    return l

def raw_recog_beam(
    start_offset: float, pa: PhoneAligner, emissions: torch.Tensor,
) -> tuple[list[dict], str]:

    with torch.inference_mode():
        vocab_dict = pa.tokenizer.get_vocab()  # vocab is a dict eg '<pad>':0, '<unk>':3
        toks = [  # make list ordered by token number- <pad>,<s>,</s>,<unk>
            token for token, idx in sorted(vocab_dict.items(), key=lambda item: item[1])
        ]
        decoder_params = {
            "tokens": toks,
            "lm": None,
            "lexicon": None,
            "nbest": 1,
            "beam_size": 50,
            "blank_token": "<pad>",
            "sil_token": "<pad>",
            "unk_word": "<unk>",
        }
        # constructing decoder each time is inefficent but fine for experiments.
        beam_decoder: torchaudio.models.decoder.CTCDecoder = ctc_decoder(decoder_params)  # type:ignore
        hypothesis = beam_decoder(emissions)
        tokens = hypothesis[0][0].tokens
        text = pa.tokenizer.decode(tokens)
        return phone_align(start_offset, text, pa, emissions), text
    # if we took this seriously by sentence, need to crop results and do beam_chars = crop_highlight_end(beam_chars, end, found_phones)
    # speedups available eg storing sentence emissions separately, tokens..
    # actual : recognise highlight_text, align highlight only.
    # could have two different tensoraudios in the state: one for sentence one for highlight
    # highlight could even check sentence to see if same?


def raw_recog(
    start_offset: float, pa: PhoneAligner, emissions: torch.Tensor) -> tuple[list[dict], str]:

    normalised: torch.Tensor = torch.softmax(emissions[0], dim=-1)
    greedyprobs, greedypred_ids = torch.max(normalised, dim=-1)
    greedy_chars = tokenpath_to_spans(
        greedypred_ids, greedyprobs, pa, start_offset)
    phones = ""
    for x in greedy_chars:
        phones += x["text"]
    if greedy_chars and greedy_chars[0]["start"] > start_offset:
        greedy_chars.insert(
            0, # insert blank at start of list
            {
                "text": "",
                "start": start_offset,
                "end": greedy_chars[0]["start"],
                "score": 0,
            },
        )
    return greedy_chars, phones

#using the emissions of the phone model, return times and scores for
#each phone in the string given.
def phone_align(
    start_time_offset: float,
    phones: str,
    pa:PhoneAligner, 
    emissions: torch.Tensor,
) -> list[dict]:
    
    logger=logging.getLogger("DAL")
    token_list = pa.tokenizer(phones, do_phonemize=False)

    # for i in token_list.input_ids :
    #         d=tokenizer.decoder.get(i,'???')
    #         print(f" {i=} {d}")

    with torch.inference_mode():
        logprobs: torch.Tensor = F.log_softmax(
            emissions, dim=-1
        )  # dim=-1 is the vocabulary dimension. logits->logprobs normalize.

        #logger.info("Aligning. %d %d",logprobs.shape[1],len(token_list.input_ids))
        while logprobs.shape[1] < len(token_list.input_ids):
           logger.info("TOO MANY TOKENS: %s, removing some.",phones)
           logger.info(token_list)
           token_list.input_ids.pop()

        targets: torch.Tensor = torch.tensor(
            [token_list.input_ids],
            dtype=torch.int32,
            device=pa.device,
        )
        #logger.info("Size of alignments: %d,%d",logprobs.shape[1],len(token_list.input_ids))
        aligned_tokens, scores = torchaudio.functional.forced_align(logprobs, targets)
        scores: torch.Tensor = scores.exp()  # convert back to probability


    return tokenpath_to_spans(
        aligned_tokens[0], scores[0],pa, start_time_offset
    )

#Use new audio segment to construct and return one sentence's worth of audio, and its length.
#if is_sentence is true, this is trivially the new segment provided.
#if not, extract full sentence from big_audio, and splice the new segment into the middle.
def construct_retry_audio(
    seg: numpy.ndarray,
    is_sentence: bool,
    sent_start: float,
    sent_end: float,
    seg_start: float,
    seg_end: float,
    big_audio_in: numpy.ndarray,
    unit_time,
) -> tuple[numpy.ndarray, float]:
    if is_sentence:
        audio = seg
    else:
        audio = (
            big_audio_in[int(unit_time * sent_start) : int(unit_time * seg_start)]
            + seg
            + big_audio_in[int(unit_time * seg_end) : int(unit_time * sent_end)]
        )
    return audio, len(seg) * unit_time

# calculate minimum size of audio sample needed for this model (used for padding)
def get_receptive_field_samples(model) -> int:

    receptive_field = 1
    accumulated_stride = 1

    for kernel_size, stride in zip(
        model.config.conv_kernel,
        model.config.conv_stride,
    ):
        receptive_field += (kernel_size - 1) * accumulated_stride
        accumulated_stride *= stride

    return receptive_field

# For a given audio array in numpy format, do not modify it
# but extract between start and end time and convert to tensors.
# run phone model over it. return audio tensors, and result tensors.

def process_phone_audio(audio_in: numpy.ndarray, pa: PhoneAligner, start: float, end: float) -> tuple[torch.Tensor, torch.Tensor]: 

    minimum_samples = get_receptive_field_samples(pa.model)
    audio = torch.from_numpy(audio_in)

    if len(audio.shape) == 1:
        audio = audio.unsqueeze(0)

    audio = audio[:, int(pa.sample_rate * start) : int(pa.sample_rate * end)]

    if audio.shape[-1] < minimum_samples:
        audio = torch.nn.functional.pad(audio, (0, minimum_samples - audio.shape[-1]))

    with torch.inference_mode():
        emissions = pa.model(audio.to(pa.device)).logits

    return audio, emissions

