# Recording Day Checklist

This checklist is for the Samsung PRISM demo branch. It separates ordinary voice validation from intentional race tests so fake latency does not make every take slow.

## 1. Normal recording profile

Use this for almost every take:

```bash
export INTERLOCK_MODE=DEMO
export INTERLOCK_TOOL_TIMEOUT_MS=15000
export INTERLOCK_FAKE_LATENCY_MS=0

export INTERLOCK_VOICE_STT_LANGUAGE='en-IN'
export INTERLOCK_VOICE_STT_ENDPOINTING_MS=500
export INTERLOCK_VOICE_STT_UTTERANCE_END_MS=1000
export INTERLOCK_VOICE_FINAL_COALESCE_MS=700
```

Restart the backend and LiveKit worker after changing voice settings.

Run:

```bash
bash scripts/recording_preflight.sh
```

Do not record the final demo if the automated preflight fails.

## 2. Natural phrases you can use

Fresh booking examples:

```text
I'd like eleven.
Can we do twelve?
Twelve please.
Eleven please.
Let's do twelve.
Go with eleven.
Go for twelve.
Yeah twelve.
Eleven works.
At twelve please.
Please book me for eleven.
Can you schedule it for twelve?
Reserve eleven.
Book eleven in the morning.
Book twelve in the afternoon.
Twelve o'clock please.
Give me midday please.
Book an appointment for noon.
```

Correction examples after an active booking exists:

```text
Actually twelve.
Actually book twelve.
Actually make it twelve.
No, twelve.
Sorry, twelve.
I meant twelve.
Make that twelve.
Change the booking to twelve.
Change from eleven to twelve.
Move it to twelve.
Move the appointment from eleven to twelve.
Switch it to noon.
Reschedule for twelve.
Twelve instead.
Can we do twelve instead?
Wait, make it twelve.
Set it to twelve.
Use twelve instead.
Go with noon instead.
Put it at twelve.
Cancel eleven and book twelve.
Instead of eleven, book twelve.
Replace eleven with twelve.
```

The same forms generally work in the opposite direction for eleven.

Supported canonical demo values are exactly 11:00 and 12:00. Common voice forms include eleven, eleven AM, eleven o'clock, eleven in the morning, twelve, twelve PM, twelve o'clock, noon, midday, and numeric 11/12 forms.

## 3. Inputs that must clarify instead of guessing

```text
Eleven or twelve.
Maybe eleven, maybe twelve.
Book 11:30.
Book eleven thirty.
Half past eleven.
Quarter to twelve.
Around twelve.
Before twelve.
After eleven.
Maybe book twelve.
Book by twelve.
```

Negations must never normalize into a positive write:

```text
Don't book twelve.
Do not book twelve.
Actually do not make it twelve.
```

## 4. Manual acceptance matrix

For every scenario inspect the exact final STT transcript, desired slot, operation count, provider physical write count, authoritative reality/effect, divergence state, and speech result.

| Scenario | Spoken sequence | Expected |
| --- | --- | --- |
| Natural 11 | `I'd like eleven.` | desired 11, reality 11, one write |
| Natural 12 | `Can we do twelve?` | desired 12, reality 12, one write |
| Noon alias | `Give me midday please.` | books 12 |
| Simple correction | initial 11, then `Sorry, twelve.` | desired changes to 12 |
| Reverse correction | initial 12, then `I meant eleven.` | desired changes to 11 |
| From/to correction | initial 11, then `Change from eleven to twelve.` | destination is 12 |
| Replacement wording | initial 11, then `Instead of eleven, book twelve.` | destination is 12 |
| Missing value | active booking, then `Actually change it.` | targeted slot clarification, no new write |
| Ambiguous | `Eleven or twelve.` | clarification, zero writes |
| Unsupported slot | `Book 11:30.` | clarification, zero writes |
| Negation | fresh session, `Don't book twelve.` | zero positive writes |
| Duplicate input | repeat the same booking quickly | no duplicate physical booking |
| Barge-in | interrupt audible assistant speech with a valid correction | old speech terminalizes, new input remains usable |
| Missing final STT | force/no-final transcript condition | controlled repeat prompt, no write |
| Two rooms | room A eleven, room B noon | isolated intent/provider/effects |

## 5. Early cancellation / SAFEPOINT scenario

Use the normal profile with zero fake latency:

```text
Pause.
I'd like eleven.
No, twelve.
Resume.
```

Before Resume:

```text
old 11 operation = CANCELLED
cancellation acknowledgement includes LOCAL_TASK
old effect = NOT_STARTED
old dispatch_requested_event_id = none
provider physical writes = 0
active desired slot = 12
```

After Resume:

```text
exactly one provider write
only 12 dispatches
desired = 12
reality = 12
no 11 effect
no divergence
```

## 6. Post-provider delayed-result race

Only for this scenario restart the backend with:

```bash
export INTERLOCK_TOOL_TIMEOUT_MS=15000
export INTERLOCK_FAKE_LATENCY_MS=10000
```

Then:

```text
Let's do eleven.
Actually twelve.
```

The current fake delay happens after the simulated provider has acted, so this deliberately represents a crossed external boundary, not a pre-dispatch delay.

Expected:

```text
desired = 12
physical 11 may already exist
provider writes = 1
no blind 12 write
authoritative reality = 11 when the late result is observed
divergence = OPEN
no false "12 is booked" speech
```

## 7. Late correction

With normal zero latency:

```text
Eleven works.
(wait for full confirmation)
Make that twelve.
```

Expected:

```text
desired = 12
reality = 11
old 11 remains historical truth
no automatic 12 repair
divergence = OPEN
TRUTHLOCK does not claim 12 is booked
```

## 8. Intentional timeout safety

If fake latency exceeds tool timeout, the provider may have acted while INTERLOCK cannot observe the result in time. The demo must remain OUTCOME_UNKNOWN and must not fabricate success. The recording branch intentionally defers unavailable automatic verification rather than surfacing an unrelated protocol-violation error.

Do not use this configuration for the main promo take.

## 9. Final recording sequence

Recommended clean narrative:

```text
1. Fresh room
2. "I'd like eleven."
3. Show intent / operation starting
4. "Actually twelve."
5. Show desired = 12 while authoritative reality retains 11 in the crossed-boundary race
6. Show OPEN mismatch
7. Show TRUTHLOCK uncertainty / correction
8. Expand Black Box for causal events
```

Before recording, close old rooms/tabs, restart backend + worker + frontend, verify the microphone permission, use headphones if possible to reduce speaker echo, and create a fresh session.
