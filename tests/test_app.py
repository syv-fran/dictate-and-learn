import json
import logging
import time

import pytest


def wait_for_log(caplog, target_message, expecting_error=False, timeout=20.0):
    start_time = time.time()
    while time.time() - start_time < timeout:
        t:str=caplog.text
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
    response3 = client.get('/static/')
    response4 = client.get('/static/index.html')
    assert response.data==response2.data==response3.data==response4.data

def test_unknown_page(client):
    response = client.get("/abeoib")
    assert response.status_code == 404

def test_recognize_preset(client,caplog):
    with caplog.at_level(logging.INFO, logger="app"): 
        caplog.clear()
        response = client.post("/start_recog",data={'model': 'tiny'})       
        assert response.status_code == 202
        wait_for_log(caplog,"READY")
        response = client.get("/get_recog")
        assert response.status_code == 200
        json_data = response.get_json()
        wordlist=json_data['words']
        ok =  ( json_data['is_partial'] == False and 
                len(wordlist)>10 and 
                len(wordlist)<40 and 
                any(x['word']=="dignidade" and x['sent']==1 for x in wordlist))
        if not ok:
            pretty_json = json.dumps(json_data, indent=4)
            print(f"{pretty_json}")
            assert False, "Bad json conditions!"
        
        wait_for_log(caplog,"Loaded synthesis model")

        w=wordlist[10]
        print(w)
        response=client.get('/analyze',
                            query_string={'start':w['start'],'end':w['end'],'sent':w['sent'],'text':w['word']})
        print(response)
        assert response.status_code == 200
        json_data = response.get_json()
        l=json_data['list']
        p=json_data['phones']
        assert l
        assert p

        response=client.get('/analyze',
                            query_string={'start':w['start'],'end':w['end'],'sent':w['sent']})
        assert response.status_code == 200
        json_data = response.get_json()
        l=json_data['list']
        p=json_data['phones']
        assert l
        assert p

        response=client.get('/analyze',
                            query_string={'start':w['start'],'end':w['end'],'sent':w['sent'],'beam':1})
        assert response.status_code == 200
        json_data = response.get_json()
        l=json_data['list']
        p=json_data['phones']
        assert l
        assert p

        assert "ERROR" not in caplog.text #final check, avoid race conditions

def test_phoneme(client):             
    response = client.get("/phoneme_info")
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data['n']
    assert len(json_data['n'])==3

def test_bad_analysis_request(client):
    response=client.get('/analyze',query_string={'start':1})
    assert response.status_code == 400

def test_analysis_empty(client):
    response=client.get('/analyze',query_string={'start':'0','end':'0','sent':'0'})
    json_data = response.get_json()
    assert json_data['list']==[] and json_data['phones']==''

def test_recognize_unknown_lang(client, caplog):
    with caplog.at_level(logging.INFO, logger="app"):
        caplog.clear()
        response = client.post("/start_recog", data={"lang":'xxx'})
        assert response.status_code == 202
        wait_for_log(caplog, "not a valid language code", expecting_error=True)

def test_recognize_unknown_model(client, caplog):
    with caplog.at_level(logging.INFO, logger="app"):
        caplog.clear()
        response = client.post("/start_recog", data={"model": "notamodel"})
        assert response.status_code == 202
        wait_for_log(caplog, "Invalid model size", expecting_error=True)


# to do: submit actual audio from preset. check we have a partial result, and that
# full result contains is_unlikely and scores.
# voice synth test
# later: testsuite for retry analysis