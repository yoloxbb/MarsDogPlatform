"""Speech orchestration runs with explicit ports and memory state, without ROS."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields
from types import SimpleNamespace as NS
from unittest.mock import Mock
import threading
import time
from marsdog_voice_interaction.core import speech_pipeline as pipeline
from marsdog_voice_interaction.core.speech_pipeline_ports import SpeechPorts, SpeechRuntime, MemorySpeechState


def runtime(asr, *, background=False):
    state=MemorySpeechState(interaction_id='i',latest_wake_id='w')
    emitted=[]; parsed=[]; completions=[]
    deps={f.name:None for f in fields(SpeechPorts)}
    deps.update(perf_counter=time.perf_counter, new_utterance_id=lambda:'generated', providers={'asr':NS(transcribe=asr)}, state_machine=NS(trigger=Mock()),
        speaker_operation_lock=threading.Lock(),clean_text=lambda text:text.strip(),
        wakeup_supersedes_utterance=lambda wake:wake!=state.latest_wake_id,
        refresh_for_asr_result=Mock(),trace=Mock(),publish=emitted.append,
        select_kws_candidate=lambda **kw:(None,'no_candidate'),trace_recognition_arbitration=Mock(),
        parse_intent=lambda text,**kw:parsed.append((text,kw)) or {'intent':'NONE'},
        complete_intent=lambda result,**kw:completions.append((result,kw)) or True)
    if background:
        deps['providers']['intent_llm']=NS(background_intent=True,is_available=lambda:True)
    return SpeechRuntime(state,SpeechPorts(**deps)),emitted,parsed,completions


def process(rt):
    return pipeline.process_speech(rt,{},'u',ThreadPoolExecutor=ThreadPoolExecutor,
        logger=Mock(),speaker_to_voice_event=lambda speaker:'speaker_result')


def test_plain_ports_preserve_raw_asr_and_ordering():
    rt,events,parsed,complete=runtime(lambda audio:{'asr_text':' hello ','language':'en'})
    assert process(rt)
    assert [e['event_type'] for e in events]==['speaker_result','speech']
    assert parsed==[('hello',{'raw_text':' hello '})]
    assert complete[0][1]['utterance_wake_id']=='w'


def test_new_wake_during_provider_call_discards_old_work():
    def transcribe(audio):
        rt.state.latest_wake_id='new'
        return {'asr_text':'sit'}
    rt,events,parsed,complete=runtime(transcribe)
    assert not process(rt)
    assert not events and not parsed and not complete


def test_background_pending_state_has_single_owner_and_no_worker_publication():
    rt,events,parsed,complete=runtime(lambda audio:{'asr_text':'hello'},background=True)
    try:
        assert process(rt)
        interaction,context,future=rt.state.pending_intent
        assert interaction=='i' and context['utterance_id']=='u'
        assert future.result(timeout=2)=={'intent':'NONE'}
        assert not complete
        assert len(events)==2
    finally:
        rt.state.intent_executor.shutdown(wait=True)
