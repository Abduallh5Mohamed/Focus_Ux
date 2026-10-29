---
name: Private-preview worker access
description: External Windows connection and platform-access constraints for the GPU worker.
---

Use the main app's Networking URL for an external worker after the implementation is merged, not an isolated task's preview URL. Successful requests inside the workspace do not establish external reachability. Keep platform access and application worker authorization separate; never follow redirects carrying credentials.

**Why:** The operator's Windows worker loaded models but redirected on the task preview. Comparison showed a different main URL without the unmerged worker routes. The operator corrected an assumption about the screenshot: private preview had only just been disabled for testing, not necessarily earlier. A subsequent task-host check still redirected. Treating a task redirect as proof of a main-preview privacy problem caused unnecessary settings navigation.

**How to apply:** Establish which environment an operator's screenshot and worker address refer to before diagnosing access; do not infer an earlier setting from a screenshot taken after a change. Check external reachability before loading models. For a genuinely private main preview, consult current official documentation and check Development external-access-token availability; token controls require prior private publication. Do not publish a task fork or change preview privacy without authorization.
