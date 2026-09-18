# Speech and Output

The output planner creates SpeechActs for progress, clarification, result, failure, uncertainty, divergence, or correction. Consequential acts use controlled templates; nonconsequential explanation may use model phrasing after policy validation. Approved acts enter one ordered session queue and produce start/finish events through a text/TTS `OutputPort`.

`CANCEL_SPEECH` removes queued acts and asks the adapter to stop current playback; it does not cancel operations. Already played audio remains `EMITTED`. Progressive Truth advances only when corresponding evidence exists, and skips stages a provider cannot prove. Adapter failure emits a failure event and retains approved text for UI. Tests: T-SPK-01.
