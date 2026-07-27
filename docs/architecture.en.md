# Architecture

Mic captures or replays audio, then sends 16 kHz RTP media and canonical control events to Orchestrator. Orchestrator owns ASR and all cross service decisions. Mic is mode agnostic, so `lecturer`, `virtual_streamer`, and `onsite_explainer` do not change its contract.
