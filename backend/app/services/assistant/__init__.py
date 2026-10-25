"""The assistant (roadmap M3): "Ask nexdeck", for administrators.

It answers from what nexdeck already knows (the cards, the chronicle, the
outages, the history) through tools that only read. It never presses a
button: it proposes one, with what the button would hit, and the person
presses it. It reads a container's log only after the person allowed it, in
that conversation.

Off by default. An administrator chooses the provider under System: Claude,
or any service that speaks the OpenAI form (OpenAI, Ollama, LM Studio and
the like). Whether questions leave the house is said in the chat itself.
"""
