# IPC

Initial transport: Unix domain socket.

Requirements: - filesystem permissions restrict clients; - validate peer
credentials; - request contains operation, user/session context and
timeout; - response contains only authentication result and diagnostic
status; - never return embeddings or frames; - reject
malformed/oversized requests.
