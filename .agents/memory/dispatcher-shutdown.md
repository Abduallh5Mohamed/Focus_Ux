---
name: Dispatcher shutdown policy
description: Why a shutdown timeout must preserve exclusive ownership and database access.
---

Treat a bounded shutdown timeout as an explicit failure, not cancellation of inference. Preserve exclusive ownership and repository access until shutdown can be retried successfully.

**Why:** Extraction runs synchronously in a Python thread and may outlast the shutdown budget. Releasing ownership could allow replacement recovery to corrupt a live job; closing storage could prevent the original worker from persisting its result. An explicit failure was chosen over waiting indefinitely.

**How to apply:** Keep shutdown failures visible. Do not put repository close or lock release into unconditional cleanup around a timed-out worker join. If changing inference to cancellable execution, establish that it has actually stopped before releasing resources.
