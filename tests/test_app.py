import io
import json
import logging
import time

import pytest

from flask import Response
from backend.words import to_basiclist


def wait_for_log(caplog, target_message, expecting_error=False, timeout=30.0):
    start_time = time.time()
    while time.time() - start_time < timeout:
        t: str = caplog.text
        if (not expecting_error) and "ERROR" in t:
            pytest.fail(f"ERROR received: {t}")
        elif target_message in t:
            return True
        time.sleep(0.1)
    pytest.fail(f"Thread failed to log '{target_message}' within {timeout} seconds.")


def test_home_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Dictate" in response.data
    response2 = client.get("/index.html")
    response3 = client.get("/static/")
    response4 = client.get("/static/index.html")
    assert response.data == response2.data == response3.data == response4.data


def test_unknown_page(client):
    response = client.get("/abeoib")
    assert response.status_code == 404


def test_tips(client, caplog):
    raw = [
        {"text": "s", "start": 0.0, "end": 0.2, "score": 0.4},
        {"text": "o", "start": 0.2, "end": 0.5, "score": 0.2},
    ]
    corr = [
        {"text": "k", "start": 0.0, "end": 0.2, "score": 0.3},
        {"text": "a", "start": 0.2, "end": 0.5, "score": 0.2},
    ]
    best = [   
        {"text": "t", "start": 0.0, "end": 0.2, "score": 0.8},
        {"text": "e", "start": 0.2, "end": 0.5, "score": 0.6},
        ]

    payload = {
        "corr": list(map(to_basiclist, corr)),
        "best": list(map(to_basiclist, best)),
        "raw": list(map(to_basiclist, raw)),
    }
    response = client.post("/tips", json=payload)
    assert response.status_code == 200
    tips = response.get_json()
    assert any("Adjust your speech from o to a" in tip for tip in tips)


def test_recognize_preset(client, caplog):
    with caplog.at_level(logging.INFO, logger="app"):
        caplog.clear()
        response = client.post("/start_recog", data={"model": "tiny"})
        assert response.status_code == 202
        wait_for_log(caplog, "READY ANALYSIS")
        response = client.get("/get_recog")
        assert response.status_code == 200
        json_data = response.get_json()
        wordlist = json_data["words"]
        ok = (
            json_data["is_partial"] == False
            and len(wordlist) > 10
            and len(wordlist) < 40
            and any(x["word"] == "dignidade" and x["sent"] == 1 for x in wordlist)
        )
        if not ok:
            pretty_json = json.dumps(json_data, indent=4)
            print(f"{pretty_json}")
            assert False, "Bad json conditions!"
        wait_for_log(caplog, "READY COMPLETE")
        wait_for_log(caplog, "Loaded synthesis model")

        w = wordlist[10]
        print(w)
        response = client.get(
            "/analyze",
            query_string={
                "start": w["start"],
                "end": w["end"],
                "sent": w["sent"],
                "text": w["word"],
            },
        )
        print(response)
        assert response.status_code == 200
        json_data = response.get_json()
        l = json_data["list"]
        p = json_data["phones"]
        assert l
        assert p

        response = client.get(
            "/analyze",
            query_string={"start": w["start"], "end": w["end"], "sent": w["sent"]},
        )
        assert response.status_code == 200
        json_data = response.get_json()
        l = json_data["list"]
        p = json_data["phones"]
        assert l
        assert p

        response = client.get(
            "/analyze",
            query_string={
                "start": w["start"],
                "end": w["end"],
                "sent": w["sent"],
                "beam": 1,
            },
        )
        assert response.status_code == 200
        json_data = response.get_json()
        l = json_data["list"]
        p = json_data["phones"]
        assert l
        assert p

        assert "ERROR" not in caplog.text  # final check, avoid race conditions


def test_phoneme(client):
    response = client.get("/phoneme_info")
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data["n"]
    assert len(json_data["n"]) == 3


def test_bad_analysis_request(client):
    response = client.get("/analyze", query_string={"start": 1})
    assert response.status_code == 400


def test_analysis_empty(client):
    response = client.get(
        "/analyze", query_string={"start": "0", "end": "0", "sent": "0"}
    )
    json_data = response.get_json()
    assert json_data["list"] == [] and json_data["phones"] == ""


def test_actual_audio(client, caplog):
    with caplog.at_level(logging.INFO, logger="app"):
        caplog.clear()
        response: Response = client.get("/static/preset.mp3")
        assert response.status_code == 200
        audio = response.get_data()
        assert len(audio)
        print(len(audio))
        response = client.post(
            "/start_recog",
            data={
                "model": "tiny",
                "audio": (io.BytesIO(audio), "myinput.mp3"),
            },
        )
        assert response.status_code == 202
        wait_for_log(caplog, "PARTIAL")
        wait_for_log(caplog, "READY COMPLETE")
        response = client.get("/get_recog")
        assert response.status_code == 200
        json_data = response.get_json()
        assert json_data["lang"]
        wordlist = json_data["words"]
        ok = (
            json_data["is_partial"] == False
            and len(wordlist) > 10
            and len(wordlist) < 40
            and "unlikely" in wordlist[0]
            and "score" in wordlist[0]
        )
        if not ok:
            pretty_json = json.dumps(json_data, indent=4)
            print(f"{pretty_json}")
            assert False, "Bad json conditions!"


def test_recognize_unknown_lang(client, caplog):
    with caplog.at_level(logging.INFO, logger="app"):
        caplog.clear()
        response = client.post("/start_recog", data={"lang": "xxx"})
        assert response.status_code == 202
        wait_for_log(caplog, "not a valid language code", expecting_error=True)


def test_recognize_unknown_model(client, caplog):
    with caplog.at_level(logging.INFO, logger="app"):
        caplog.clear()
        response = client.post("/start_recog", data={"model": "notamodel"})
        assert response.status_code == 202
        wait_for_log(caplog, "Invalid model size", expecting_error=True)


# to do later: voice synth test
# to do later: testsuite for retry analysis
