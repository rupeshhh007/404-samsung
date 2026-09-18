# AI Usage

Development agents implement reviewed tickets, preserve contracts, write/run tests, and report uncertainty honestly. They have no authority to redefine the product or claim tests/integrations ran when they did not.

Runtime models have narrower permissions: classify `ControlIntent`, extract `IntentDelta`, suggest bounded branches, and propose temporal anchors via the exact structured prompts in `LLM_CONTRACTS`. Outputs are untrusted JSON, schema/confidence validated, and converted to events only by deterministic policy. Models never mutate state, authorize actions, call tools, or establish external truth.

User-facing language has a separate boundary. A model may help phrase nonconsequential explanation, but consequential `SpeechAct` content passes TRUTHLOCK and controlled templates. It cannot turn pending/unknown into confirmed. Human/user authorization is required where the intent/descriptor/reconciliation plan says so and is bound to exact arguments.

On model timeout, invalid output, or absence, one format repair is allowed where documented, then scripted fallback or clarification. Prompt injection is data. Tests use deterministic stubs and label them; demo UI labels `SIMULATED`, `SCRIPTED`, `MODEL-ASSISTED`, and real runtime policy. Test reports state actual execution status. Unsupported claims—by code-writing agents or runtime models—must be corrected explicitly.
