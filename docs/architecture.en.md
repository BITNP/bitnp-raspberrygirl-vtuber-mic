# Architecture

Mic is a hub client that connects only to Orchestrator. `mic-stream` opens authenticated WSS control, binds its configured local UDP socket, registers a source route, waits for `media.rtp.source.ready`, and sends RTP only to the configured Orchestrator UDP ingress. It has no peer-service addresses or connections. Orchestrator owns ASR and cross-service decisions.

The media contract is one fixed RTP V2/PT96/L16 packet for each complete 16 kHz mono capture block: 320 samples, 20 ms, and 640 payload bytes. `mic-capture` uses `sounddevice` with PortAudio only as a local one-frame stdout diagnostic. Mic is strategy agnostic, so product scenarios and Orchestrator interaction choices do not change its contract.
